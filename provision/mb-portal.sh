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
AP_SSID="MagicBridge-Setup"
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
online(){ ip route 2>/dev/null | grep -q '^default' || return 1
          ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; }

setup_ap(){
    systemctl stop "wpa_supplicant@${AP_IFACE}" 2>/dev/null
    systemctl stop wpa_supplicant 2>/dev/null
    rfkill unblock wifi 2>/dev/null   # a soft-blocked radio otherwise = a dead hotspot (DIY handoff #6)
    ip link set "$AP_IFACE" up
    ip addr flush dev "$AP_IFACE" 2>/dev/null
    ip addr add "${AP_IP}/24" dev "$AP_IFACE"
    cat > /tmp/mb-hostapd.conf <<EOF
interface=$AP_IFACE
driver=nl80211
ssid=$AP_SSID
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
    pkill -f "hostapd /tmp/mb-hostapd" 2>/dev/null
    pkill -f "dnsmasq.*mb-dnsmasq" 2>/dev/null
    sleep 1
    hostapd -B /tmp/mb-hostapd.conf -P /tmp/mb-hostapd.pid
    sleep 1
    dnsmasq -C /tmp/mb-dnsmasq.conf --pid-file=/tmp/mb-dnsmasq.pid
    iptables -t nat -A PREROUTING -i "$AP_IFACE" -p tcp --dport 80  -j DNAT --to-destination "${AP_IP}:${PORT}" 2>/dev/null
    iptables -t nat -A PREROUTING -i "$AP_IFACE" -p tcp --dport 443 -j DNAT --to-destination "${AP_IP}:${PORT}" 2>/dev/null
    echo "[$(date)] AP '$AP_SSID' up — portal on ${AP_IP}:${PORT}"
}

teardown_ap(){
    pkill -F /tmp/mb-hostapd.pid 2>/dev/null
    pkill -F /tmp/mb-dnsmasq.pid 2>/dev/null
    iptables -t nat -F PREROUTING 2>/dev/null
    ip addr flush dev "$AP_IFACE" 2>/dev/null
}

save_wifi(){
    local SSID PASS
    SSID=$(sed -n '1p' "$WIFI_FILE"); PASS=$(sed -n '2p' "$WIFI_FILE")
    echo "[$(date)] saving WiFi '$SSID' (password ${#PASS} chars)"
    mb_rw
    # ensure the conf has a usable header (harmless if it already does)
    if ! grep -q '^ctrl_interface=' "$WPA_CONF" 2>/dev/null; then
        printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n' > /tmp/mbwpa.$$
        cat "$WPA_CONF" >> /tmp/mbwpa.$$ 2>/dev/null
        cp /tmp/mbwpa.$$ "$WPA_CONF"; rm -f /tmp/mbwpa.$$
    fi
    # append a plaintext-passphrase block (no wpa_passphrase — it choked on the
    # SSID/space before; wpa_supplicant accepts a quoted ASCII psk directly)
    if [ -n "$PASS" ]; then
        printf '\nnetwork={\n\tssid="%s"\n\tpsk="%s"\n}\n' "$SSID" "$PASS" >> "$WPA_CONF"
    else
        printf '\nnetwork={\n\tssid="%s"\n\tkey_mgmt=NONE\n}\n' "$SSID" >> "$WPA_CONF"
    fi
    mb_ro
    echo "[$(date)] wpa conf now lists $(grep -c 'ssid=' "$WPA_CONF" 2>/dev/null) network(s)"
    # optional Tailscale auth key
    if [ -f "$TS_KEY" ]; then cp "$TS_KEY" /run/mb-tskey 2>/dev/null; fi
    rm -f "$WIFI_FILE" "$TS_KEY"
}

# ---------------- main ----------------
# On boot, give any saved WiFi ~40s to associate + get DHCP before deciding to AP.
for i in $(seq 1 8); do
    sleep 5
    if online; then echo "[$(date)] network is up — nothing to do"; [ -x "$OLED" ] && "$OLED" --resume; exit 0; fi
done

# No network -> provisioning. Keep the hotspot up until someone submits creds;
# then save + reboot (a clean boot connects reliably). Wrong creds => next boot
# has no network => hotspot returns, so this effectively retries until connected.
while true; do
    setup_ap
    [ -x "$OLED" ] && "$OLED" "WiFi setup needed" "Join hotspot:" "$AP_SSID"
    echo "[$(date)] waiting for credentials (no timeout) ..."
    rm -f "$WIFI_FILE" "$TS_KEY"
    python3 "$PORTAL" "$AP_IP" "$PORT" "$WIFI_FILE" "$TS_KEY"   # blocks until submit
    if [ -f "$WIFI_FILE" ]; then
        teardown_ap
        save_wifi
        echo "[$(date)] rebooting to connect ..."
        sync; sleep 2; reboot; exit 0
    fi
    echo "[$(date)] portal exited without credentials — reopening hotspot"
    teardown_ap
done
