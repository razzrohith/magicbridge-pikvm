#!/usr/bin/env bash
# ============================================================
#  mb-firstboot-late.sh — POST-boot first-run finalize (part 2).
#
#  Runs ONCE, AFTER the full system is up (kvmd, capture device, filesystems),
#  never in the early boot path. This is deliberate and load-bearing: the early
#  mb-firstboot must stay fast and boot-critical (WiFi provisioning depends on it
#  finishing), so anything that (a) needs the live capture device, or (b) does a
#  slow/large disk operation, is done HERE instead. Nothing here can block boot or
#  the WiFi loop — by the time this runs, mb-firstboot has already written its
#  marker and the unit is on the network.
#
#    1. Grow the virtual-media (MSD) partition to fill the card (ONLINE resize).
#    2. Give this unit a UNIQUE EDID monitor serial. The early mb-firstboot EDID
#       step runs before /dev/kvmd-video exists, so the serial randomize only
#       reliably takes here. Identity stays a real Dell P2419H.
#
#  Marker-guarded -> runs exactly once per unit, so the EDID serial and MSD size
#  stay STABLE afterward. Every step is best-effort; a failure just means a
#  smaller MSD or the baked EDID serial, never a broken/looping unit.
# ============================================================
set +e
MARKER=/var/lib/magicbridge/.mb-firstboot-late-done
ROOT=/opt/magicbridge
LOG=/run/mb-firstboot-late.log
exec >> "$LOG" 2>&1
echo "[$(date)] mb-firstboot-late starting"
[ -e "$MARKER" ] && { echo "already done — nothing to do"; exit 0; }

mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }
mb_ro(){ command ro 2>/dev/null || mount -o remount,ro / ; }

# 1. Grow MSD to fill the card (online; no-ops if already full). Out of the boot
#    path on purpose — an offline resize needs an unmount kvmd won't allow, and a
#    forced fsck on a huge fs is slow.
if [ -f "$ROOT/provision/mb-expand-msd.sh" ]; then
    echo "growing MSD to fill the card"
    bash "$ROOT/provision/mb-expand-msd.sh"
fi

# 2. Unique per-unit EDID monitor serial (the target still reads a real Dell
#    P2419H; only the serial differs per unit, so units don't cross-link).
if command -v kvmd-edidconf >/dev/null 2>&1 && [ -e /dev/kvmd-video -o -e /dev/video0 ]; then
    suf=$(tr -dc A-Z </dev/urandom 2>/dev/null | head -c2 || true)
    monser="CN$(printf '%05d' $((RANDOM % 100000)))${suf:-ZA}"
    echo "EDID monitor serial -> $monser"
    mb_rw
    kvmd-edidconf --set-mfc-id DEL --set-monitor-name "DELL P2419H" \
        --set-product-id 16473 --set-serial $((RANDOM * RANDOM + 1)) \
        --set-monitor-serial "$monser" --apply >/dev/null 2>&1
    mb_ro
fi

# 2b. Defensive net for handoff 24-i: a fresh flash ships with SSH keys + TLS cert
#     STRIPPED, so if sshd/kvmd-nginx somehow started before mb-firstboot
#     regenerated them (a slow-keygen race), they'd be dead with nothing to restart
#     them. We're normally safe (mb-firstboot is Before=sysinit, so keys exist
#     first — verified live), but recover here as belt-and-suspenders. Restart ONLY
#     if actually failed, and ONLY from here (post-boot): doing this INSIDE
#     mb-firstboot would deadlock, because kvmd-nginx is ordered after it (24-ii).
for svc in sshd kvmd-nginx; do
    if systemctl is-failed --quiet "$svc" 2>/dev/null; then
        echo "recovering failed $svc (24-i)"
        systemctl restart "$svc" 2>/dev/null
    fi
done

# 2c. (REMOVED) main-login nginx rate-limit. mb-nginx-ratelimit.sh was verified
#     on real hardware to apply cleanly BUT NOT actually throttle: nginx `limit_req`
#     does not engage under kvmd's rendered nginx config even with the exact
#     `location = /api/auth/login` confirmed matching (a bare `return 418` fired).
#     Shipping a rate-limit that doesn't limit is worse than none, so it's not run.
#     Brute-force protection for the SENSITIVE face (the stealth identity panel) is
#     the in-code per-IP lockout in magicbridge-stealth, which IS verified working.

# 3. Mark done — force rw first (same lesson as mb-firstboot: mb-anon-defaults /
#    the EDID block above may have left the rootfs read-only, and a silent RO
#    write here would make this re-run every boot and re-randomize the EDID).
mb_rw
mkdir -p "$(dirname "$MARKER")" 2>/dev/null
date > "$MARKER" 2>/dev/null
[ -e "$MARKER" ] || echo "WARNING: failed to write $MARKER"
sync
mb_ro
echo "[$(date)] mb-firstboot-late done"
exit 0
