#!/usr/bin/env bash
# ============================================================
#  mb-wifi-latency.sh — kill Wi-Fi power management on wlan0.
#
#  The Broadcom Wi-Fi (brcmfmac) on the CM4 enables power-save by default: it
#  parks the radio between packets and takes 100+ ms to wake, so an otherwise
#  idle link swings from ~3 ms to 130+ ms latency and drops packets in bursts.
#  For a KVM that is exactly the wrong trade — it turns into visible video
#  stutter, missing frames, and a fat jitter buffer (added latency) on the
#  WebRTC path. Measured on this unit: avg RTT ~41 ms with spikes to 139 ms
#  power-save ON, dropping toward single-digit ms with it OFF.
#
#  Idempotent, best-effort, never fails the boot. Re-run on every wlan0 appear
#  (the .service BindsTo the device) so a reconnect can't silently re-enable it.
# ============================================================
set +e
IFACE="${1:-wlan0}"

command -v iw >/dev/null 2>&1 || { echo "iw not present — skipping"; exit 0; }
[ -e "/sys/class/net/$IFACE" ] || { echo "$IFACE not present — skipping"; exit 0; }

iw dev "$IFACE" set power_save off 2>/dev/null
state="$(iw dev "$IFACE" get power_save 2>/dev/null)"
echo "wlan0 power-save -> ${state:-unknown}"
exit 0
