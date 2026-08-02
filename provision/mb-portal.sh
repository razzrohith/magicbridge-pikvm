#!/usr/bin/env bash
# ============================================================
#  MagicBridgeV2 WiFi provisioning AP (captive portal)
#
#  Boot service (mb-portal.service). If the device has no working network it
#  raises an open "MagicBridge-Setup" hotspot + captive portal and keeps it up
#  until someone submits WiFi credentials. It SAVES the creds and reboots to
#  apply them (a clean boot connects reliably; switching wlan0 out of AP mode
#  in place is flaky on the brcmfmac driver). If the password was wrong / the
#  network is out of range, the next boot has no network so the hotspot simply
#  comes back — provisioning effectively loops until it actually connects.
#
#  PiKVM OS: WiFi = wpa_supplicant@wlan0.service + systemd-networkd (DHCP).
#  SSID: MagicBridge-Setup (open)   Portal: http://192.168.73.1/
# ============================================================
set +e

LOG="/run/mb-portal.log"
# De-branded, per-unit setup SSID. "MagicBridge-Setup" beaconed the product name
# over the air from the real Pi radio — anyone within range could identify the
# device (and, with several clones, count the fleet) without touching the network.
# "Setup-XXXX" is generic and unit-specific; the OLED shows this exact string, so
# the owner always knows which network to join. Falls back if machine-id is absent.
_apsuf="$(cut -c1-4 /etc/machine-id 2>/dev/null | tr 'a-f' 'A-F')"
[ -n "$_apsuf" ] || _apsuf="$(tr -dc 'A-F0-9' </dev/urandom 2>/dev/null | head -c4)"
[ -n "$_apsuf" ] || _apsuf="0001"
AP_SSID="Setup-${_apsuf}"
AP_IP="192.168.73.1"
AP_IFACE="wlan0"
PORT=8080
PORTAL="/opt/magicbridge/provision/portal.py"
WIFI_FILE="/tmp/mb-provision-wifi"
TS_KEY="/tmp/mb-provision-tskey"
WPA_CONF="/etc/wpa_supplicant/wpa_supplicant-${AP_IFACE}.conf"
OLED="/usr/local/bin/mb-oled-msg"
exec >> "$LOG" 2>&1
echo "[$(date)] mb-portal starting"

# NOTE: name these mb_rw/mb_ro, NOT rw/ro — a function named rw calling `rw`
# recurses into itself forever (bash resolves the name to the function, not the
# /usr/bin/rw helper) and crashes the script mid-save.
mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }
mb_ro(){ command ro 2>/dev/null || mount -o remount,ro / ; }
# "Online" means we have a usable NETWORK — not necessarily public internet.
# Requiring an ICMP reply from 1.1.1.1/8.8.8.8 was wrong: any network that blocks
# outbound ICMP (most corporate / hotel / guest Wi-Fi) or simply has no internet
# made a perfectly connected unit look offline. setup_ap then STOPS wpa_supplicant
# and FLUSHES the address — actively destroying a working connection and stranding
# the owner in the setup hotspot. A default route plus a real global address is the
# correct test. The AP's own 192.168.73.1 and link-local 169.254.x must NOT count.
online(){
    ip route 2>/dev/null | grep -q '^default' || return 1
    ip -4 -o addr show scope global 2>/dev/null \
        | grep -vE "169\.254\.|${AP_IP//./\\.}" | grep -q . || return 1
    return 0
}

# Give the saved network another chance without permanently sitting in AP mode.
# Used between provisioning cycles: the router may merely have been slow or
# rebooting, and previously nothing ever re-checked once we entered the AP loop.
try_reconnect(){
    teardown_ap
    systemctl start "wpa_supplicant@${AP_IFACE}" 2>/dev/null
    for _r in $(seq 1 6); do
        sleep 5
        online && return 0
    done
    return 1
}

# Scan for nearby SSIDs while the radio is STILL IN MANAGED MODE and cache the
# list. portal.py used to shell out to `iw dev wlan0 scan` on every HTTP GET — an
# active off-channel scan on an AP-mode interface, once per captive-portal probe.
# That is the source of the brcmfmac "set chanspec ... fail, reason -52" storm, it
# knocked the AP off channel mid-page-load, and it added up to 14s to every request.
prescan_ssids(){
    { iw dev "$AP_IFACE" scan 2>/dev/null | sed -n 's/^[[:space:]]*SSID: \(.\+\)$/\1/p' \
        | awk 'NF && !seen[$0]++' | head -25; } > /run/mb-ssids 2>/dev/null
    echo "[$(date)] pre-scanned $(wc -l < /run/mb-ssids 2>/dev/null || echo 0) SSIDs"
}

setup_ap(){
    systemctl stop "wpa_supplicant@${AP_IFACE}" 2>/dev/null
    systemctl stop wpa_supplicant 2>/dev/null
    rfkill unblock wifi 2>/dev/null   # a soft-blocked radio otherwise = a dead hotspot (DIY handoff #6)
    # Set the regulatory domain explicitly. `country=US` lives only in the
    # wpa_supplicant conf, and we just stopped wpa_supplicant — so nothing ever set
    # the regdomain and the radio ran in the world domain ("00"), which marks
    # channels NO_IR and cuts TX power. That is what turned every scan / IE update
    # into the brcmfmac "reason -52" errors seen on the first flashed unit.
    iw reg set US 2>/dev/null
    ip link set "$AP_IFACE" up
    ip addr flush dev "$AP_IFACE" 2>/dev/null
    cat > /tmp/mb-hostapd.conf <<EOF
interface=$AP_IFACE
driver=nl80211
ssid=$AP_SSID
country_code=US
ieee80211d=1
hw_mode=g
channel=6
auth_algs=1
wmm_enabled=0
EOF
    cat > /tmp/mb-dnsmasq.conf <<EOF
interface=$AP_IFACE
except-interface=lo
bind-dynamic
dhcp-range=192.168.73.10,192.168.73.50,12h
dhcp-leasefile=/run/mb-dnsmasq.leases
dhcp-authoritative
address=/#/$AP_IP
no-resolv
no-hosts
EOF
    # `-f` is a REGEX over the full command line, and the real one is
    # "hostapd -B /tmp/mb-hostapd.conf" — the old literal "hostapd /tmp/mb-hostapd"
    # could never match, so a stale hostapd survived and a SECOND one was launched
    # on wlan0. The two then fought over the interface and the AP flapped or never
    # enabled, leaving the unit unreachable.
    pkill -f 'hostapd .*mb-hostapd' 2>/dev/null
    pkill -f "dnsmasq.*mb-dnsmasq" 2>/dev/null
    sleep 1
    hostapd -B /tmp/mb-hostapd.conf -P /tmp/mb-hostapd.pid
    # Assign the AP address AFTER hostapd, and confirm it stuck. hostapd's nl80211
    # init switches wlan0 from managed to AP mode, which takes the netdev DOWN — and
    # Linux flushes every IPv4 address on NETDEV_DOWN. Adding it beforehand (as we
    # did) meant 192.168.73.1 was GONE moments later: portal.py died with
    # "[Errno 99] Cannot assign requested address", and dnsmasq — bind-dynamic with
    # dhcp-range 192.168.73.x on an interface holding no address in that subnet —
    # could not hand out leases either. A phone joining MagicBridge-Setup got no IP
    # and no page: the hotspot looked alive but provisioning was impossible.
    for _a in $(seq 1 20); do
        ip -4 addr show dev "$AP_IFACE" 2>/dev/null | grep -q "$AP_IP" && break
        ip addr add "${AP_IP}/24" dev "$AP_IFACE" 2>/dev/null
        sleep 1
    done
    if ! ip -4 addr show dev "$AP_IFACE" 2>/dev/null | grep -q "$AP_IP"; then
        echo "[$(date)] WARNING: $AP_IP never came up on $AP_IFACE — DHCP/portal will be degraded"
    fi
    dnsmasq -C /tmp/mb-dnsmasq.conf --pid-file=/tmp/mb-dnsmasq.pid
    iptables -t nat -A PREROUTING -i "$AP_IFACE" -p tcp --dport 80  -j DNAT --to-destination "${AP_IP}:${PORT}" 2>/dev/null
    iptables -t nat -A PREROUTING -i "$AP_IFACE" -p tcp --dport 443 -j DNAT --to-destination "${AP_IP}:${PORT}" 2>/dev/null
    echo "[$(date)] AP '$AP_SSID' up — portal on ${AP_IP}:${PORT}"
}

teardown_ap(){
    pkill -F /tmp/mb-hostapd.pid 2>/dev/null
    pkill -f 'hostapd .*mb-hostapd' 2>/dev/null   # pidfile can be stale after an unclean exit
    pkill -F /tmp/mb-dnsmasq.pid 2>/dev/null
    # Delete OUR two rules explicitly. `-F PREROUTING` flushed the whole chain,
    # silently destroying any nat rule owned by kvmd, kvmd-otg, tailscale or a
    # future feature — on every loop iteration and on every successful provision.
    for _p in 80 443; do
        iptables -t nat -D PREROUTING -i "$AP_IFACE" -p tcp --dport "$_p" \
            -j DNAT --to-destination "${AP_IP}:${PORT}" 2>/dev/null
    done
    ip addr flush dev "$AP_IFACE" 2>/dev/null
}

save_wifi(){
    local SSID PASS
    SSID=$(sed -n '1p' "$WIFI_FILE"); PASS=$(sed -n '2p' "$WIFI_FILE")
    echo "[$(date)] saving WiFi '$SSID' (password ${#PASS} chars)"
    # VALIDATE BEFORE WRITING. wpa_supplicant rejects the ENTIRE config file if any
    # psk is outside 8..63 chars — so one mistyped short password doesn't just fail
    # that network, it stops wpa_supplicant starting at all, for every saved network.
    # The unit then has no WiFi, re-raises the hotspot, the user retypes, and each
    # attempt appends to an already-unparsable file: a permanent lockout from a
    # single typo. (magicbridge-net enforces >=8 already; the captive portal — the
    # ONLY path a new owner has — enforced nothing.) Quotes/backslashes would
    # likewise corrupt the block, since we write a quoted literal.
    [ -n "$SSID" ] || { echo "[$(date)] REJECTED: empty SSID"; return 1; }
    if [ -n "$PASS" ] && { [ "${#PASS}" -lt 8 ] || [ "${#PASS}" -gt 63 ]; }; then
        echo "[$(date)] REJECTED: passphrase is ${#PASS} chars (WPA requires 8-63)"
        return 1
    fi
    case "$SSID$PASS" in
        *'"'*|*'\'*) echo "[$(date)] REJECTED: SSID/passphrase contains a quote or backslash"; return 1 ;;
    esac
    mb_rw
    # ensure the conf has a usable header (harmless if it already does)
    if ! grep -q '^ctrl_interface=' "$WPA_CONF" 2>/dev/null; then
        printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n' > /tmp/mbwpa.$$
        cat "$WPA_CONF" >> /tmp/mbwpa.$$ 2>/dev/null
        cp /tmp/mbwpa.$$ "$WPA_CONF"; rm -f /tmp/mbwpa.$$
    fi
    # REPLACE, never blind-append (handoff 26b). Drop any existing block for this
    # SSID first: a previously mistyped password would otherwise stay in the conf
    # forever, and on a retry wpa_supplicant would hold TWO blocks for the same
    # SSID — it can keep re-trying the bad one, so the corrected password never
    # takes. Deleting the bad profile is the equivalent of DIY's "delete the bad
    # NM connection on failure".
    python3 - "$WPA_CONF" "$SSID" <<'PY' 2>/dev/null
import re, sys
path, ssid = sys.argv[1], sys.argv[2]
try:
    txt = open(path).read()
except Exception:
    sys.exit(0)
# wpa network blocks never nest, so [^}]* is a safe block matcher.
new = re.sub(r'\n?network=\{[^}]*ssid="%s"[^}]*\}\n?' % re.escape(ssid), '\n', txt)
if new != txt:
    open(path, 'w').write(new)
PY

    # append a plaintext-passphrase block (no wpa_passphrase — it choked on the
    # SSID/space before; wpa_supplicant accepts a quoted ASCII psk directly)
    if [ -n "$PASS" ]; then
        printf '\nnetwork={\n\tssid="%s"\n\tpsk="%s"\n}\n' "$SSID" "$PASS" >> "$WPA_CONF"
    else
        printf '\nnetwork={\n\tssid="%s"\n\tkey_mgmt=NONE\n}\n' "$SSID" >> "$WPA_CONF"
    fi
    # CONFIRM the credentials actually persisted before we reboot on the strength of
    # them. mb_rw can fail (concurrent remount, missing /usr/bin/rw helper) and the
    # append then vanishes silently — we rebooted anyway, came up with no WiFi, and
    # the portal's own DONE page told the user "the password was wrong", sending
    # them round an endless loop while typing the CORRECT password.
    if ! grep -q "ssid=\"$SSID\"" "$WPA_CONF" 2>/dev/null; then
        echo "[$(date)] SAVE FAILED — credentials did not persist (rootfs still read-only?)"
        mb_ro
        return 1
    fi
    # Guarantee WiFi actually comes up next boot. PiKVM ships wpa_supplicant@wlan0
    # disabled by default; if an image is ever built from a base without the enable
    # symlink, saved credentials would never be used and the unit would loop in the
    # hotspot forever. Idempotent, and must run while / is still writable.
    systemctl enable "wpa_supplicant@${AP_IFACE}" 2>/dev/null
    mb_ro
    echo "[$(date)] wpa conf now lists $(grep -c 'ssid=' "$WPA_CONF" 2>/dev/null) network(s)"
    # optional Tailscale auth key
    if [ -f "$TS_KEY" ]; then cp "$TS_KEY" /run/mb-tskey 2>/dev/null; fi
    rm -f "$WIFI_FILE" "$TS_KEY"
    return 0
}

# ---------------- main ----------------
# On boot, give any saved WiFi up to ~90s to associate + get DHCP before deciding
# to raise the AP. 40s was too short: cold-boot association plus DHCP on a busy
# 2.4GHz band routinely takes 30-60s on brcmfmac. Timing out early is destructive,
# not neutral — setup_ap stops wpa_supplicant and flushes the address, so a slow
# but perfectly good connection was actively torn down and the owner was dumped
# into the setup hotspot with their credentials already saved. Exactly what the
# first flashed unit did.
for i in $(seq 1 18); do
    sleep 5
    if online; then echo "[$(date)] network is up — nothing to do"; [ -x "$OLED" ] && "$OLED" --resume; exit 0; fi
done
echo "[$(date)] no network after 90s — entering provisioning"

# No network -> provisioning. Keep the hotspot up until someone submits creds;
# then save + reboot (a clean boot connects reliably). Wrong creds => next boot
# has no network => hotspot returns, so this effectively retries until connected.
_fastexits=0
_cycles=0
while true; do
    # RECOVERY: before re-raising the AP, give the saved network another chance.
    # Previously online() was never re-evaluated once we entered this loop, so a
    # router that was merely slow or rebooting left the unit parked in AP mode
    # forever — with wpa_supplicant stopped — even though it would have connected.
    if [ "$_cycles" -gt 0 ] && try_reconnect; then
        echo "[$(date)] network returned — leaving provisioning"
        [ -x "$OLED" ] && "$OLED" --resume
        exit 0
    fi
    _cycles=$(( _cycles + 1 ))
    # Cache the SSID list while the radio is still in managed mode (see prescan_ssids).
    prescan_ssids
    setup_ap
    [ -x "$OLED" ] && "$OLED" "WiFi setup needed" "Join hotspot:" "$AP_SSID"
    # Drop a Windows/macOS-readable report on the FAT boot partition each time the
    # hotspot comes up. If the AP or portal is broken, this is how a user with only
    # a card reader can see WHY (hostapd state, who holds :80, portal log) — the
    # ext4 logs are unreadable off-Pi. Best-effort; never blocks provisioning.
    # RATE-LIMITED: writing it remounts the FAT /boot read-write and rewrites ~4KB.
    # This ran on EVERY loop iteration — and in the portal-crash mode each iteration
    # was ~13s, so /boot was being remounted+rewritten continuously and forever. A
    # power cut inside one of those windows corrupts the boot partition and the unit
    # stops booting at all; it is also pointless SD wear. First cycle, then 5-minutely.
    _now=$(date +%s); _lastrep=$(cat /run/mb-lastreport 2>/dev/null || echo 0)
    if [ "$_cycles" -le 1 ] || [ $(( _now - _lastrep )) -ge 300 ]; then
        echo "$_now" > /run/mb-lastreport 2>/dev/null
        [ -f /opt/magicbridge/provision/mb-boot-report.sh ] && bash /opt/magicbridge/provision/mb-boot-report.sh hotspot-up 2>/dev/null
    fi
    echo "[$(date)] waiting for credentials (no timeout) ..."
    rm -f "$WIFI_FILE" "$TS_KEY"
    _pstart=$(date +%s)
    python3 "$PORTAL" "$AP_IP" "$PORT" "$WIFI_FILE" "$TS_KEY"   # blocks until submit
    if [ -f "$WIFI_FILE" ]; then
        # Verify + re-raise is handled BY DESIGN across a reboot, not in place:
        # we save the creds and reboot. The next boot polls connectivity for ~40s
        # (the `online` loop above); if the password was wrong there's no network,
        # so this same script raises the hotspot again for a retry. So we never
        # announce "Connected" prematurely and the AP always comes back on failure
        # — the failure mode DIY hit (AP torn down before confirming) can't happen.
        teardown_ap
        # Only reboot if the credentials were valid AND actually persisted. We used
        # to reboot unconditionally, so a rejected/lost save sent the user round the
        # loop while the DONE page blamed their password.
        if save_wifi; then
            echo "[$(date)] rebooting to connect ..."
            sync; sleep 2; reboot; exit 0
        fi
        echo "[$(date)] credentials rejected or not persisted — re-raising hotspot"
        continue
    fi
    teardown_ap
    # Runaway guard (handoff 26d): if the portal EXITED IMMEDIATELY (crash / :8080
    # busy) rather than a human closing the page, don't churn hostapd up/down in a
    # tight loop — back off, and after a few fast exits drop a diagnostic report to
    # PIBOOT. We never permanently give up (a human may still join), we just avoid
    # the runaway that would be worse than the original bug.
    _pelapsed=$(( $(date +%s) - _pstart ))
    if [ "$_pelapsed" -lt 5 ]; then
        _fastexits=$(( _fastexits + 1 ))
        echo "[$(date)] portal exited in ${_pelapsed}s (fast exit #$_fastexits) — backing off"
        [ "$_fastexits" -ge 3 ] && [ -f /opt/magicbridge/provision/mb-boot-report.sh ] && \
            bash /opt/magicbridge/provision/mb-boot-report.sh portal-crash 2>/dev/null
        sleep 10
    else
        _fastexits=0
        echo "[$(date)] portal closed without credentials after ${_pelapsed}s — reopening hotspot"
    fi
done
