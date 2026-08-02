#!/usr/bin/env bash
# ============================================================
#  mb-secret-reset.sh — MagicBridge per-unit secret reset (PiKVM / kvmd).
#
#  Regenerates every secret that must be UNIQUE per physical unit, so a golden
#  image never ships shared credentials/keys — which would let units impersonate
#  each other and be cross-linked (a hard break of the anonymity model).
#
#  Run once by mb-firstboot.sh on a flashed unit; safe to re-run. Adapted (idea,
#  not code) from DIY's mb-secret-reset: that stack is NetworkManager +
#  /etc/magicbridge; here it's kvmd + wpa_supplicant + /etc/kvmd.
# ============================================================
set +e
info(){ echo "[$(date)] secret-reset: $*"; }
# Same nested-caller rule as mb-anon-defaults: mb-firstboot invokes us inside its
# own rw window, so only return / to read-only if WE made it writable. Otherwise
# every later step in the caller silently fails on a read-only rootfs.
_MB_WAS_RW=0
case ",$(awk '$2=="/"{print $4; exit}' /proc/mounts 2>/dev/null)," in *,rw,*) _MB_WAS_RW=1 ;; esac
mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }
mb_ro(){ [ "$_MB_WAS_RW" = 1 ] && return 0
         command ro 2>/dev/null || mount -o remount,ro / ; }
mb_rw

# 1. SSH host keys — otherwise every unit shares one host identity.
info "regenerating SSH host keys"
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A >/dev/null 2>&1

# 2. machine-id — a cross-linkable per-install identifier.
info "regenerating machine-id"
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup >/dev/null 2>&1
ln -sf /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null

# 3. kvmd TLS cert/key (nginx + vnc) — self-signed, must be unique per unit.
#    UNCONDITIONAL on purpose: build-image.sh strips these from a distributable
#    image, so "regenerate only if present" would skip here and leave the unit
#    with NO cert — kvmd-nginx then fails to start and the flashed unit is dead.
#    Always (re)create the dir + keypair. Stock PiKVM certs are also identical
#    across every install of an OS build, so replacing them is a real win.
for d in /etc/kvmd/nginx/ssl /etc/kvmd/vnc/ssl; do
    info "regenerating TLS certificate in $d"
    mkdir -p "$d" 2>/dev/null
    # CN/SAN = THIS unit's own hostname, never a branded fleet-wide name.
    # "/CN=magicbridge.local" on every unit is a pre-auth, ssl-cert-scannable
    # beacon: anyone sweeping a network (or Shodan/censys) can fingerprint every
    # MagicBridge in existence without authenticating, AND cross-link clones to
    # each other by their identical certificate subject. The hostname is already a
    # realistic per-unit DESKTOP-XXXXXXX, so the cert now looks like any Windows box.
    _cn="$(cat /etc/hostname 2>/dev/null | tr -d '[:space:]')"
    [ -n "$_cn" ] && [ "$_cn" != "magicbridge" ] || _cn="DESKTOP-$(tr -dc A-Z0-9 </dev/urandom 2>/dev/null | head -c7 || echo GENERIC)"
    openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout "$d/server.key" -out "$d/server.crt" \
        -subj "/CN=${_cn}" \
        -addext "subjectAltName=DNS:${_cn},DNS:${_cn}.local,IP:127.0.0.1" >/dev/null 2>&1
    chmod 600 "$d/server.key" 2>/dev/null
    chmod 644 "$d/server.crt" 2>/dev/null
done
# Hand each cert to the service user that reads it (kvmd-nginx / kvmd-vnc).
chown kvmd-nginx: /etc/kvmd/nginx/ssl/server.key /etc/kvmd/nginx/ssl/server.crt 2>/dev/null
chown kvmd-vnc:   /etc/kvmd/vnc/ssl/server.key   /etc/kvmd/vnc/ssl/server.crt   2>/dev/null

# 4. Auth back to defaults + drop our secret/identity state (no baked creds/keys).
# Default login is magicbridge/magicbridge (kept in sync with kvmd.json below,
# which the sidecars use to call kvmd's API). The stealth panel default password
# ("stealthbridge") comes from /etc/magicbridge/stealth_auth.json — we only clear
# the per-unit override in the writable state dir so it falls back to that default.
# ---- PER-UNIT RANDOM CREDENTIALS -----------------------------------------
# A golden image that bakes the SAME web password into every clone means one leak
# unlocks the whole fleet — and this one ("magicbridge") is published in our own
# repo and docs. Generate a fresh password per unit for BOTH panels. A fresh unit
# is headless, so surface them on the FAT boot partition, which any OS can read
# with a card reader (same escape-hatch channel as the setup report).
MB_PW="$(tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 14)"
[ "${#MB_PW}" -ge 10 ] || MB_PW="mb$(date +%s)$$"
MB_SPW="$(tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 14)"
[ "${#MB_SPW}" -ge 10 ] || MB_SPW="sb$(date +%s)$$"

if command -v kvmd-htpasswd >/dev/null 2>&1; then
    info "setting a unique per-unit kvmd web password"
    # kvmd-htpasswd edits an EXISTING file — if the store is missing (e.g. an image
    # that stripped it) every add/set below fails silently and the unit ends up with
    # NO web login. Reseed from PiKVM's own shipped default first, else an empty file.
    if [ ! -f /etc/kvmd/htpasswd ]; then
        info "htpasswd store missing — recreating it"
        cp /usr/share/kvmd/configs.default/kvmd/htpasswd /etc/kvmd/htpasswd 2>/dev/null \
            || : > /etc/kvmd/htpasswd
        chown kvmd:kvmd /etc/kvmd/htpasswd 2>/dev/null
        chmod 600 /etc/kvmd/htpasswd 2>/dev/null
    fi
    # 'add' creates the user (fresh unit has only 'admin'); 'set' updates on re-run.
    printf '%s\n' "$MB_PW" | kvmd-htpasswd add -i magicbridge >/dev/null 2>&1 \
        || printf '%s\n' "$MB_PW" | kvmd-htpasswd set -i magicbridge >/dev/null 2>&1
    kvmd-htpasswd del admin >/dev/null 2>&1 || true
fi
# mkdir first: every other missing-file case here is defended, but this one wasn't
# — with /etc/magicbridge absent the write fails silently and all three sidecars
# (magicbridge-net/-stealth/-agent) come up with NO kvmd API credentials.
mkdir -p /etc/magicbridge 2>/dev/null
printf '{\n  "user": "magicbridge",\n  "passwd": "%s",\n  "base": "https://127.0.0.1/api"\n}\n' \
    "$MB_PW" > /etc/magicbridge/kvmd.json 2>/dev/null
chmod 600 /etc/magicbridge/kvmd.json 2>/dev/null
[ -s /etc/magicbridge/kvmd.json ] || info "WARNING: could not write /etc/magicbridge/kvmd.json"

# Stealth panel: same treatment. Scheme is sha256(salt + password) — see
# magicbridge-stealth/app.py:_hash_pw. We write the INSTALL default here; the
# per-unit override in /var/lib/magicbridge is cleared below, so this takes effect.
info "setting a unique per-unit stealth-panel password"
_salt="$(tr -dc 'a-f0-9' </dev/urandom 2>/dev/null | head -c 16)"
_hash="$(printf '%s' "${_salt}${MB_SPW}" | sha256sum 2>/dev/null | cut -d' ' -f1)"
if [ -n "$_salt" ] && [ -n "$_hash" ]; then
    printf '{\n  "salt": "%s",\n  "hash": "%s"\n}\n' "$_salt" "$_hash" > /etc/magicbridge/stealth_auth.json 2>/dev/null
    chmod 600 /etc/magicbridge/stealth_auth.json 2>/dev/null
fi

# Surface the credentials where a headless owner can actually read them: the FAT
# boot partition. Without this a randomized password would simply lock them out.
_bootrw=0; mount -o remount,rw /boot 2>/dev/null && _bootrw=1
{
    echo "==============================================="
    echo " MagicBridge — THIS UNIT'S LOGIN DETAILS"
    echo " Generated on first boot. Unique to this device."
    echo "==============================================="
    echo ""
    echo "  Web cockpit (https://<device-ip>/)"
    echo "     user     : magicbridge"
    echo "     password : $MB_PW"
    echo ""
    echo "  Stealth panel (/stealth/)"
    echo "     password : $MB_SPW"
    echo ""
    echo "Change both from the UI after first login."
    echo "Delete this file once you have saved the passwords."
} > /boot/magicbridge-credentials.txt 2>/dev/null
chmod 600 /boot/magicbridge-credentials.txt 2>/dev/null
sync
[ "$_bootrw" = 1 ] && mount -o remount,ro /boot 2>/dev/null
[ -s /boot/magicbridge-credentials.txt ] || info "WARNING: could not write credentials to /boot"
: > /etc/kvmd/totp.secret 2>/dev/null

# 4b. kvmd's OTHER credential stores: ipmipasswd + vncpasswd. Both services ship
#     DISABLED, but the files still hold PiKVM's stock "admin" credential — a
#     factory tell, and one every unit flashed from a golden image would share.
#     Normalize to the MagicBridge default so nothing stock-PiKVM ships. Keep the
#     kvmd-owned modes; these files are 0600 and owned by their service users.
if [ -f /etc/kvmd/ipmipasswd ]; then
    info "resetting kvmd IPMI credential (stock 'admin' is a PiKVM tell)"
    printf '# IPMI users in format "login:password", one per line. NOT encrypted.\nmagicbridge:magicbridge\n' \
        > /etc/kvmd/ipmipasswd 2>/dev/null
    chown kvmd-ipmi:kvmd-ipmi /etc/kvmd/ipmipasswd 2>/dev/null
    chmod 600 /etc/kvmd/ipmipasswd 2>/dev/null
fi
if [ -f /etc/kvmd/vncpasswd ]; then
    info "resetting kvmd VNC credential (stock 'admin' is a PiKVM tell)"
    printf '# Passwords for the legacy VNCAuth, one per line. NOT encrypted.\nmagicbridge\n' \
        > /etc/kvmd/vncpasswd 2>/dev/null
    chown kvmd-vnc:kvmd-vnc /etc/kvmd/vncpasswd 2>/dev/null
    chmod 600 /etc/kvmd/vncpasswd 2>/dev/null
fi
rm -f /var/lib/magicbridge/net.json /var/lib/magicbridge/stealth.json \
      /var/lib/magicbridge/stealth_auth.json /var/lib/magicbridge/agent.json \
      /var/lib/magicbridge/macros.json 2>/dev/null

# 5. USB gadget serial — drop our OTG override so a FRESH realistic serial is
#    generated on the next gadget build (the stealth service re-emits one).
info "clearing USB identity override (serial regenerates)"
rm -f /etc/kvmd/override.d/90-magicbridge-otg.yaml 2>/dev/null

# 6. Saved WiFi + MAC persistence — provision fresh, don't join the builder's net.
# NEVER destroy WiFi the OWNER entered. build-image.sh already blanks this conf
# offline, so a genuinely fresh flash reaches here with no saved network and the
# wipe below is a no-op anyway. The dangerous case is a RE-RUN: if first-boot ever
# repeats (marker write failed, TimeoutStartSec kill, power cut before the marker),
# an unconditional wipe deletes the credentials the user just typed and drops the
# unit back into the setup hotspot — the provisioning loop, on a unit the owner
# already configured. Set MB_FORCE_WIPE=1 to force (mb-imageprep does its own wipe).
if [ "${MB_FORCE_WIPE:-0}" = "1" ] || ! grep -q 'ssid=' /etc/wpa_supplicant/wpa_supplicant-wlan0.conf 2>/dev/null; then
    info "clearing saved WiFi + MAC persistence"
    printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n' \
        > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf 2>/dev/null
else
    info "KEEPING saved WiFi (already provisioned — refusing to strand the owner)"
fi
rm -f /etc/systemd/network/70-mb-*.link 2>/dev/null
# Reset hostname to a placeholder tell so mb-anon-defaults regenerates a fresh
# per-unit DESKTOP-XXXXXXX on this clone (the builder's name must not persist).
info "resetting hostname (regenerated per unit)"
hostnamectl set-hostname magicbridge 2>/dev/null
printf 'magicbridge\n' > /etc/hostname 2>/dev/null

# 7. Tailscale — don't inherit the builder's node identity.
info "clearing Tailscale state"
tailscale logout >/dev/null 2>&1
systemctl stop tailscaled >/dev/null 2>&1
rm -f /var/lib/tailscale/tailscaled.state* /var/lib/tailscale/derpmap.cache 2>/dev/null
rm -rf /var/lib/tailscale/certs 2>/dev/null

# 8. RAM logs / provisioning leftovers.
rm -f /run/mb-*.log /tmp/mb-* 2>/dev/null

# ---- FAIL-CLOSED verification -------------------------------------------
# Everything above is best-effort (set +e). We then exited 0 unconditionally and
# mb-firstboot stamped "first-boot done" — so ONE silent failure shipped a unit
# with a SHARED (or absent) identity that never retried. This is not theoretical:
# a non-executable script meant NONE of these steps ran, and the unit still marked
# itself finalized, shipping with no SSH host keys and no TLS cert at all.
# Verify the artifacts that MUST be unique-per-unit and return non-zero if any is
# missing, so first-boot leaves its marker unset and simply retries next boot.
_fail=0
_chk(){ if eval "$2"; then info "ok: $1"; else info "FAIL: $1"; _fail=1; fi; }
_chk "SSH host keys"     'ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1'
_chk "machine-id"        '[ -s /etc/machine-id ]'
_chk "nginx TLS keypair" '[ -s /etc/kvmd/nginx/ssl/server.key ] && [ -s /etc/kvmd/nginx/ssl/server.crt ]'
_chk "vnc TLS keypair"   '[ -s /etc/kvmd/vnc/ssl/server.key ]'
_chk "web login store"   '[ -s /etc/kvmd/htpasswd ]'
_chk "sidecar creds"     '[ -s /etc/magicbridge/kvmd.json ]'
# Without this file a randomized password locks the owner out of their own device.
_chk "credentials on /boot" '[ -s /boot/magicbridge-credentials.txt ]'
_chk "web password is NOT the old shared default" '! grep -q "\"passwd\": \"magicbridge\"" /etc/magicbridge/kvmd.json 2>/dev/null'
mb_ro
if [ "$_fail" != 0 ]; then
    info "SECRET RESET INCOMPLETE — refusing to look finalized; will retry on next boot"
    exit 1
fi
info "done"
exit 0
