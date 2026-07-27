#!/usr/bin/env bash
# ============================================================
#  ⚠ DISABLED / DOES NOT WORK — kept for reference only. Verified on real hardware
#  (172.16.20.171, 2026-07-21): this applies cleanly and the web UI stays up, BUT
#  nginx `limit_req` NEVER THROTTLES under kvmd's rendered config. The exact
#  `location = /api/auth/login` was confirmed to match (a bare `return 418` fired
#  from it), the zone is defined at http context, yet 25 rapid logins all returned
#  200 and even an aggressive rate=2r/m/burst=1 didn't reject a single request. No
#  `real_ip` rewrite and the client hits :443 directly, so `$binary_remote_addr`
#  should be valid — root cause needs deeper nginx-level debugging. NOTHING calls
#  this; the stealth-panel in-code lockout is the working brute-force protection.
#
#  mb-nginx-ratelimit.sh — brute-force rate-limit the kvmd web login.
#
#  The stealth panel has its own per-IP lockout (in magicbridge-stealth), but the
#  MAIN login (POST /api/auth/login) is handled by kvmd directly, so the only clean
#  place to throttle it is nginx. This adds an nginx `limit_req` to that ONE
#  endpoint — ~12 attempts/min per IP (a human logs in occasionally; a brute-forcer
#  is throttled), leaving the rest of the UI (video, HID) completely untouched.
#
#  ⚠ SAFE BY CONSTRUCTION: nginx zone/config errors can take down the web server,
#  and this may run where `nginx -t` isn't easy to pre-check. So it APPLIES then
#  VERIFIES, and fully REVERTS if kvmd-nginx doesn't reload cleanly — the running
#  web server is never left down. Idempotent. Meant to run POST-boot (mb-firstboot-
#  late) or from the installer, NEVER in the boot-critical path.
# ============================================================
set +e
MAKO=/etc/kvmd/nginx/nginx.conf.mako
RL=/etc/kvmd/nginx/magicbridge-ratelimit.conf
ZONE='limit_req_zone $binary_remote_addr zone=mb_login:10m rate=12r/m;'

mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }
mb_ro(){ command ro 2>/dev/null || mount -o remount,ro / ; }

[ -f "$MAKO" ] || { echo "no kvmd nginx mako — skipping"; exit 0; }
# Already applied and healthy? no-op.
if grep -q 'zone=mb_login' "$MAKO" && [ -f "$RL" ] && systemctl is-active --quiet kvmd-nginx; then
    echo "login rate-limit already present"; exit 0
fi

mb_rw

# 1. Define the rate-limit zone at HTTP context (right after kvmd's http include).
grep -q 'zone=mb_login' "$MAKO" || \
    sed -i "\|include /etc/kvmd/nginx/kvmd.ctx-http.conf;|a\\	$ZONE" "$MAKO"

# 2. The login location (server context), matching kvmd's own /api proxy pattern.
cat > "$RL" <<'EOF'
# MagicBridge: throttle the login endpoint only (see mb-nginx-ratelimit.sh).
location = /api/auth/login {
    limit_req zone=mb_login burst=5 nodelay;
    rewrite ^/api/auth/login$ /auth/login break;
    rewrite ^/api/auth/login\?(.*)$ /auth/login?$1 break;
    proxy_pass http://kvmd;
    include /etc/kvmd/nginx/loc-proxy.conf;
    auth_request off;
}
EOF
chmod 644 "$RL"
# Include it inside the :443 server, right after our main include.
grep -q 'magicbridge-ratelimit.conf' "$MAKO" || \
    sed -i "\|include /etc/kvmd/nginx/magicbridge.conf;|a\\		include /etc/kvmd/nginx/magicbridge-ratelimit.conf;" "$MAKO"

# 3. VERIFY: kvmd-nginx renders the mako + tests before reloading. If the reload
#    fails (bad config), nginx keeps the OLD config running — the web UI stays up —
#    and we REVERT our additions so a future reload/boot is clean.
if systemctl reload kvmd-nginx 2>/dev/null && sleep 2 && systemctl is-active --quiet kvmd-nginx; then
    echo "login rate-limit applied + verified"
    mb_ro
    exit 0
else
    echo "kvmd-nginx did not reload cleanly — REVERTING login rate-limit"
    sed -i '/zone=mb_login/d' "$MAKO" 2>/dev/null
    sed -i '\|include /etc/kvmd/nginx/magicbridge-ratelimit.conf;|d' "$MAKO" 2>/dev/null
    rm -f "$RL"
    systemctl reload kvmd-nginx 2>/dev/null
    mb_ro
    exit 0
fi
