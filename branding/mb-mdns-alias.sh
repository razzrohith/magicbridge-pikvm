#!/usr/bin/env bash
# Keep avahi healthy so the realistic <hostname>.local (e.g. DESKTOP-XXXXXXX.local)
# resolves, and OPTIONALLY publish extra branded aliases. Branded aliases
# (magicbridge.local, etc.) are a network tell, so they are OFF by default
# (MB_MDNS_ALIASES empty); avahi still auto-publishes the realistic hostname.
set -euo pipefail
# shellcheck disable=SC1091
[ -f /opt/magicbridge/branding/branding.env ] && source /opt/magicbridge/branding/branding.env
ALIASES="${MB_MDNS_ALIASES:-}"

# unmask + start avahi if a previous image left it masked (self-heal, lesson from V1)
systemctl unmask avahi-daemon.service avahi-daemon.socket 2>/dev/null || true
systemctl enable --now avahi-daemon.service 2>/dev/null || true

# No branded aliases configured => nothing to publish (the realistic hostname
# still resolves via avahi's automatic <hostname>.local).
[ -z "${ALIASES// /}" ] && exit 0

IP="$(hostname -I | awk '{print $1}')"
for name in $ALIASES; do
    /usr/bin/avahi-publish -a -R "${name}.local" "$IP" &
done
wait
