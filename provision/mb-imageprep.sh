#!/usr/bin/env bash
# ============================================================
#  mb-imageprep.sh — prepare a MagicBridge unit for GOLDEN IMAGING.
#
#  Run this ON a source device (one you've set up perfectly) RIGHT BEFORE you
#  snapshot its SD card to a distributable .img. It strips this unit's unique /
#  secret state and RE-ARMS first-boot, so every card flashed from the image
#  self-finalizes into a unique, clean unit (new SSH keys, fresh machine-id, its
#  own WiFi onboarding).
#
#  ⚠  This makes the card GENERIC — it will re-run first-boot (and re-onboard
#     WiFi) on its next boot. Only run it on a device you intend to turn INTO
#     the master image (or on a throwaway clone of it), never your daily unit.
#
#  After it finishes: `shutdown -h now`, pull the SD, image it (docs/IMAGING.md).
# ============================================================
set +e
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
mb_rw(){ command rw 2>/dev/null || mount -o remount,rw / ; }

echo "MagicBridge image-prep — making this card generic..."
mb_rw

# Re-arm first-boot so the flashed card runs mb-firstboot on its first power-on.
rm -f /var/lib/magicbridge/.mb-firstboot-done
rm -f /var/lib/magicbridge/.mb-firstboot-late-done   # post-boot MSD grow + EDID re-run

# Drop this unit's UNIQUE identity (regenerated per-card on first boot).
rm -f /etc/ssh/ssh_host_*
rm -f /var/lib/dbus/machine-id; : > /etc/machine-id

# Drop this unit's NETWORK + SECRET state (the image must not ship these).
printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n' \
    > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
# Strip the spoofed-MAC identity (handoff item 20): without this, every card
# flashed from a stealthed master would share ONE vendor MAC — cross-linkable +
# a LAN collision. Cleared here; mb-anon-defaults regenerates a fresh per-unit
# MAC on first boot. (DIY's companion `video.mode=auto` strip is N/A here: the
# V4 Mini is CSI-only/kvmd-native, so there is no per-unit capture mode to leak.)
rm -f /etc/systemd/network/70-mb-*.link
rm -f /var/lib/magicbridge/net.json /var/lib/magicbridge/stealth.json \
      /var/lib/magicbridge/stealth_auth.json /var/lib/magicbridge/agent.json
: > /etc/kvmd/totp.secret 2>/dev/null
# Residual-tell sweep: our neutralization of kvmd's mDNS advert leaves a
# `pikvm.service.mb-bak` backup on disk. avahi ignores non-`.service` files so it
# is never broadcast, but the backup still contains "PiKVM Web Server"/board/serial
# strings — don't ship them inside a distributable image. (Found in the item-20
# reconciliation sweep.) The active neutralized pikvm.service stays in place.
rm -f /etc/avahi/services/*.mb-bak 2>/dev/null

# Clear logs + shell history so nothing personal ships in the image.
rm -rf /var/log/* 2>/dev/null
rm -f /root/.bash_history 2>/dev/null; history -c 2>/dev/null

sync
echo
echo "✓ image-prep complete."
echo "  Next:  shutdown -h now  →  pull the SD  →  image it (see docs/IMAGING.md)"
echo "  Do NOT boot this card back into normal use — it is now a master image."
