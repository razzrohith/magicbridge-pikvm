#!/usr/bin/env bash
# ============================================================
#  mb-boot-report.sh — write a plain-text diagnostic report to the FAT boot
#  partition (PIBOOT), so a STUCK unit is still diagnosable.
#
#  Why this exists: a unit with no WiFi and no working hotspot is unreachable over
#  the network, and its real logs live on the ext4 root partition — which Windows
#  and macOS cannot read at all (and `wsl --mount` refuses removable SD readers
#  without admin). We hit exactly that: a looping unit took hours to diagnose.
#  PIBOOT is FAT, so ANY OS reads it: pull the card, open the .txt.
#
#  Called (best-effort) from mb-firstboot and mb-portal. Never fails its caller.
#
#  ⚠ Contains NO secrets: no WiFi passphrase, no keys, no certs. Only state.
# ============================================================
set +e
OUT=/boot/magicbridge-setup-report.txt
TAG="${1:-report}"

boot_rw(){ mount -o remount,rw /boot 2>/dev/null; }
boot_ro(){ mount -o remount,ro /boot 2>/dev/null; }
have(){ command -v "$1" >/dev/null 2>&1; }

boot_rw
{
  echo "==================================================================="
  echo " MagicBridge setup report   ($TAG)"
  echo " Written: $(date 2>/dev/null)"
  echo " Read this on any computer - just put the card in a reader."
  echo "==================================================================="
  echo
  echo "--- UNIT ---"
  echo "hostname   : $(hostname 2>/dev/null)"
  echo "uptime     : $(uptime -p 2>/dev/null)"
  echo "version    : $(cat /opt/magicbridge/VERSION 2>/dev/null)"
  echo "git HEAD   : $(git -C /opt/magicbridge log -1 --oneline 2>/dev/null)"
  echo
  echo "--- FIRST BOOT ---"
  echo "firstboot marker      : $( [ -e /var/lib/magicbridge/.mb-firstboot-done ] && cat /var/lib/magicbridge/.mb-firstboot-done 2>/dev/null || echo 'ABSENT  <-- first-boot has NOT completed' )"
  echo "post-boot marker      : $( [ -e /var/lib/magicbridge/.mb-firstboot-late-done ] && cat /var/lib/magicbridge/.mb-firstboot-late-done 2>/dev/null || echo 'absent (MSD/EDID finalize not done yet)' )"
  echo "mb-firstboot service  : $(systemctl is-active mb-firstboot 2>/dev/null) / result=$(systemctl show mb-firstboot -p Result --value 2>/dev/null)"
  echo "-- mb-firstboot log (tail) --"
  tail -n 25 /run/mb-firstboot.log 2>/dev/null || echo "(no log this boot)"
  echo
  echo "--- NETWORK ---"
  echo "wlan0 MAC  : $(cat /sys/class/net/wlan0/address 2>/dev/null)"
  echo "addresses  : $(ip -br addr 2>/dev/null | tr '\n' '|')"
  echo "default gw : $(ip route 2>/dev/null | grep '^default' | head -1)"
  # Headless discovery (handoff 28): this unit has NO branded mDNS name by design
  # (that would be a LAN tell), but avahi publishes its realistic per-unit hostname.
  echo "REACH ME AT: https://$(hostname 2>/dev/null).local/   (unique per unit; or use the IP above)"
  echo "avahi (mDNS): daemon=$(systemctl is-active avahi-daemon 2>/dev/null) socket=$(systemctl is-active avahi-daemon.socket 2>/dev/null)"
  echo "saved WiFi networks (count, NO passwords): $(grep -c 'ssid=' /etc/wpa_supplicant/wpa_supplicant-wlan0.conf 2>/dev/null)"
  echo "wpa_supplicant: $(systemctl is-active wpa_supplicant@wlan0 2>/dev/null)  networkd: $(systemctl is-active systemd-networkd 2>/dev/null)"
  echo
  echo "--- HOTSPOT / PROVISIONING ---"
  echo "mb-portal service : $(systemctl is-active mb-portal 2>/dev/null)"
  echo "hostapd running   : $(pgrep -a hostapd 2>/dev/null | head -1 || echo 'NO  <-- no hotspot is being broadcast')"
  echo "dnsmasq running   : $(pgrep -a dnsmasq 2>/dev/null | head -1 || echo no)"
  echo "portal process    : $(pgrep -af 'portal.py' 2>/dev/null | head -1 || echo 'not running')"
  echo "DNAT :80/:443 -> portal:"
  if have iptables; then iptables -t nat -S PREROUTING 2>/dev/null | grep -E 'dport (80|443)' || echo "  (none - captive redirect NOT installed)"; fi
  echo "-- mb-portal log (tail) --"
  tail -n 30 /run/mb-portal.log 2>/dev/null || echo "(no portal log this boot)"
  echo
  echo "--- WHO HOLDS THE WEB PORTS (:80 / :443 / :8080) ---"
  # The classic captive-portal failure is the web server owning :80. We avoid it
  # with DNAT to :8080, but record the truth so it is never a guess again.
  if have ss; then ss -lntp 2>/dev/null | grep -E ':80 |:443 |:8080 ' || echo "(nothing listening)"
  else netstat -lntp 2>/dev/null | grep -E ':80 |:443 |:8080 ' || echo "(ss/netstat unavailable)"; fi
  echo
  echo "--- SERVICES ---"
  for s in sshd kvmd kvmd-nginx kvmd-otg magicbridge-net magicbridge-stealth magicbridge-agent mb-anon-defaults mb-firstboot-late; do
    printf '%-22s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"
  done
  echo
  echo "--- STORAGE ---"
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT 2>/dev/null | grep -E 'mmcblk0|NAME'
  echo "rootfs mode: $(findmnt -no OPTIONS / 2>/dev/null | grep -o '^r[ow]')"
  echo
  echo "--- POWER / UNDER-VOLTAGE (handoff 29) ---"
  # A weak USB-C supply makes the Pi under-volt: USB devices (the HDMI capture!)
  # enumerate, work, then VANISH from lsusb with /dev/videoN gone. That looks like
  # a capture/driver bug but is really power. Surface it so it self-diagnoses.
  if command -v vcgencmd >/dev/null 2>&1; then
    _t=$(vcgencmd get_throttled 2>/dev/null)
    echo "vcgencmd    : $_t"
    case "$_t" in
      *0x0) echo "power       : OK — no under-voltage or throttling flags" ;;
      *throttled=0x*) echo "power       : ⚠ FLAGS SET — bit0=under-voltage now, bit16=under-voltage since boot. Use a real 5V/3A USB-C supply; a laptop port is NOT enough." ;;
    esac
  else
    echo "vcgencmd    : (unavailable)"
  fi
  echo "capture dev : $(ls /dev/video0 /dev/kvmd-video 2>/dev/null | tr '\n' ' ' || echo 'GONE — if it worked earlier, this is a POWER problem, not capture code')"
  echo
  echo "--- RECENT ERRORS (this boot) ---"
  journalctl -b -p err --no-pager 2>/dev/null | tail -n 20 || echo "(journal unavailable)"
  echo
  echo "==================================================================="
  echo " WHAT TO DO"
  echo " * 'firstboot marker: ABSENT' -> first-boot did not finish; it will re-run"
  echo "   and re-wipe WiFi every boot (a provisioning loop)."
  echo " * 'hostapd running: NO' while the screen says join a hotspot -> the AP"
  echo "   died; check the mb-portal log above."
  echo " * Something other than the portal on :80 with no DNAT rules -> the captive"
  echo "   portal cannot be reached."
  echo " * Under-voltage flags set (POWER section) -> capture/network dropping out is"
  echo "   a weak supply, NOT a bug. Use a proper 5V/3A USB-C supply."
  echo " * '.local doesn't resolve' from your computer -> almost always a client-side"
  echo "   VPN (NordVPN etc.) blocking LAN mDNS, not the unit. Disable it or use the IP."
  echo " Send this file to support / paste it to Claude."
  echo "==================================================================="
} > "$OUT" 2>/dev/null
sync 2>/dev/null
chmod 644 "$OUT" 2>/dev/null
boot_ro
exit 0
