#!/usr/bin/env bash
# ============================================================
#  mb-anon-defaults.sh — realistic, STABLE anonymity defaults for PiKVM/kvmd.
#
#  Makes the unit present as an ordinary PC out of the box:
#    - hostname: a realistic per-unit DESKTOP-XXXXXXX (not pikvm/raspberrypi/
#      magicbridge, all network tells via DHCP + mDNS)
#    - WiFi MAC: a real consumer-vendor OUI, persisted via a systemd-networkd
#      .link (applied at the udev layer BEFORE association, so it sticks — unlike
#      `ip link set address`, which systemd-networkd/wpa reasserts on reconnect)
#
#  IDEMPOTENT + STABLE: it generates a value ONLY if the current one is missing
#  or a known tell, then persists it and KEEPS it on every later run. It never
#  re-randomises an existing realistic value (a MAC/hostname that changes every
#  boot would itself be a tell). Per-unit uniqueness on a clone comes from
#  mb-secret-reset clearing these first, then this regenerating them.
#
#  Opt out via branding.env: MB_MAC_AUTOSPOOF=0 / MB_HOSTNAME_REALISTIC=0.
# ============================================================
set +e
LINK=/etc/systemd/network/70-mb-wlan0.link
[ -f /opt/magicbridge/branding/branding.env ] && . /opt/magicbridge/branding/branding.env 2>/dev/null

mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }
mb_ro(){ command ro 2>/dev/null || mount -o remount,ro / ; }

# A "tell" hostname is one that outs the device as a Pi/KVM/this product.
_is_tell(){ case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    ''|localhost|pikvm|raspberrypi|raspberry|magicbridge|magicbridgev2|kvm|raj) return 0;; *) return 1;; esac; }

mb_rw

# ---- Hostname: realistic DESKTOP-XXXXXXX, generated once, then stable --------
cur="$(hostname 2>/dev/null)"
if [ "${MB_HOSTNAME_REALISTIC:-1}" = "1" ] && _is_tell "$cur"; then
    # `|| true`: head closing the pipe after 7 bytes SIGPIPEs tr (rc 141); this
    # script has no `set -o pipefail` today, but the guard keeps it safe if one is
    # ever added (and mirrors DIY d52ba3f, where exactly this aborted the install).
    suf="$(tr -dc 'A-Z0-9' </dev/urandom 2>/dev/null | head -c7 || true)"
    newhost="DESKTOP-${suf:-7F3K9QZ}"; newhost="${newhost:0:15}"
    hostnamectl set-hostname "$newhost" 2>/dev/null
    printf '%s\n' "$newhost" > /etc/hostname 2>/dev/null
    echo "hostname: '$cur' was a tell -> '$newhost'"
else
    echo "hostname kept (realistic or opted out): '$cur'"
fi

# ---- WiFi MAC: realistic vendor OUI via networkd .link, generated once -------
# Real consumer OUIs (Dell / HP / Intel / Samsung) so a scan reads "a laptop",
# never "Raspberry Pi" / a bare WiFi chip.
if [ "${MB_MAC_AUTOSPOOF:-1}" = "1" ]; then
    if [ ! -f "$LINK" ]; then
        OUIS=(18:03:73 34:17:eb f8:bc:12 3c:d9:2b 98:e7:f4 80:ce:62 \
              3c:58:c2 34:41:5d a0:88:b4 e4:a4:71 78:bd:bc 8c:77:12)
        oui="${OUIS[$((RANDOM % ${#OUIS[@]}))]}"
        mac="$(printf '%s:%02x:%02x:%02x' "$oui" $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)))"
        printf '[Match]\nOriginalName=wlan0\n\n[Link]\nMACAddressPolicy=none\nMACAddress=%s\n' "$mac" > "$LINK"
        echo "MAC: created stable default -> $mac (applies on next boot; systemd-networkd keeps it)"
    else
        echo "MAC: keeping existing default ($(grep -o 'MACAddress=.*' "$LINK" 2>/dev/null))"
    fi
else
    echo "MAC autospoof opted out"
fi

# ---- Kill kvmd's mDNS product advert -----------------------------------------
# kvmd ships /etc/avahi/services/pikvm.service advertising _pikvm._tcp / _https
# with "PiKVM Web Server", "Raspberry Pi Compute Module 4", board=rpi4,
# model=v4mini and the serial — a full stack of tells to anyone doing mDNS
# discovery. Neutralise it (idempotent: only rewrite if it still has tells), so
# the realistic <hostname>.local still resolves but nothing product-y is broadcast.
AV=/etc/avahi/services/pikvm.service
if [ -f "$AV" ] && grep -qiE '_pikvm|PiKVM|Compute Module|board=rpi' "$AV" 2>/dev/null; then
    cat > "$AV" <<'XML'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<!-- Emptied by MagicBridge: the stock mDNS advert here announced the product
     name, board, model and serial over the LAN. Nothing product-identifying is
     broadcast now; the realistic host.local still resolves. -->
<service-group>
  <name replace-wildcards="yes">%h</name>
</service-group>
XML
    echo "neutralized kvmd mDNS advert ($AV)"
    systemctl is-active --quiet avahi-daemon && systemctl reload avahi-daemon 2>/dev/null
fi

mb_ro
exit 0
