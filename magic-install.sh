#!/usr/bin/env bash
# =====================================================================
#  MagicBridgeV2 — the one magic command
#  Turns a stock PiKVM OS install into a fully-branded MagicBridgeV2 unit.
#
#  Usage (on the V4 Mini, after flashing official PiKVM OS + first boot):
#     curl -fsSL https://raw.githubusercontent.com/razzrohith/MagicBridgeV2/main/magic-install.sh | sudo bash
#  or, from a local clone:
#     sudo ./magic-install.sh [--branch main] [--no-reboot] [--update] [--dry-run]
#
#  Safe & idempotent: re-running upgrades in place. Reverts with ./uninstall.sh
#  Requires: PiKVM OS (Arch Linux ARM) with kvmd. Refuses to run elsewhere.
# =====================================================================
set -Eeuo pipefail

# ---- constants ------------------------------------------------------
REPO_URL="https://github.com/razzrohith/MagicBridgeV2.git"
RAW_URL="https://raw.githubusercontent.com/razzrohith/MagicBridgeV2"
INSTALL_ROOT="/opt/magicbridge"
BRANCH="main"
DO_REBOOT=1
DRY_RUN=0
UPDATE=0
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || echo /tmp)"

# ---- pretty logging -------------------------------------------------
c_reset=$'\e[0m'; c_cyan=$'\e[38;5;51m'; c_mag=$'\e[38;5;135m'; c_grn=$'\e[38;5;46m'; c_red=$'\e[38;5;196m'; c_dim=$'\e[2m'
say()  { printf '%s▸%s %s\n' "$c_cyan" "$c_reset" "$*"; }
ok()   { printf '%s✓%s %s\n' "$c_grn"  "$c_reset" "$*"; }
warn() { printf '%s!%s %s\n' "$c_mag"  "$c_reset" "$*" >&2; }
die()  { printf '%s✗ %s%s\n' "$c_red"  "$*" "$c_reset" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then printf '%s  [dry-run] %s%s\n' "$c_dim" "$*" "$c_reset"; else eval "$@"; fi; }

banner() {
cat <<'B'
   __  __             _      ____       _     _            ___
  |  \/  | __ _  __ _(_) ___| __ ) _ __(_) __| | __ _  ___|__ \
  | |\/| |/ _` |/ _` | |/ __|  _ \| '__| |/ _` |/ _` |/ _ \ / /
  | |  | | (_| | (_| | | (__| |_) | |  | | (_| | (_| |  __// /_
  |_|  |_|\__,_|\__, |_|\___|____/|_|  |_|\__,_|\__, |\___|____|
               |___/                           |___/  V2
B
  printf '%s  Remote control, reimagined.%s\n\n' "$c_dim" "$c_reset"
}

# ---- read-only rootfs helpers (PiKVM OS) ----------------------------
FS_WAS_RO=0
fs_rw() { if command -v rw >/dev/null 2>&1; then run "rw"; else run "mount -o remount,rw /"; fi; }
fs_ro() { if [ "$FS_WAS_RO" = 1 ]; then if command -v ro >/dev/null 2>&1; then run "ro"; else run "mount -o remount,ro /"; fi; fi; }
cleanup() { fs_ro || true; }
trap cleanup EXIT
trap 'die "failed at line $LINENO"' ERR

# ---- args -----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2;;
    --no-reboot) DO_REBOOT=0; shift;;
    --update) UPDATE=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

# =====================================================================
#  Phase 0 — preflight
# =====================================================================
phase0_preflight() {
  say "Phase 0 — preflight checks"
  [ "$(id -u)" = 0 ] || die "run as root (sudo)."
  # Must be PiKVM OS with kvmd. This is the whole premise of V2.
  if ! command -v kvmd >/dev/null 2>&1 && [ ! -d /etc/kvmd ]; then
    die "kvmd not found. MagicBridgeV2 installs on top of the official PiKVM OS.
        Flash the PiKVM OS image first, boot once, then re-run this."
  fi
  # detect read-only rootfs
  if findmnt -no OPTIONS / | grep -qw ro; then FS_WAS_RO=1; say "read-only rootfs detected — will toggle rw during install"; fi
  ok "PiKVM OS + kvmd detected"
}

# =====================================================================
#  Phase 1 — fetch MagicBridgeV2 into place
# =====================================================================
phase1_fetch() {
  say "Phase 1 — fetch MagicBridgeV2 ($BRANCH)"
  fs_rw
  run "mkdir -p '$INSTALL_ROOT'"
  if [ -d "$SELF_DIR/services" ] && [ -f "$SELF_DIR/branding/branding.env" ]; then
    say "installing from local clone: $SELF_DIR"
    run "cp -a '$SELF_DIR/.' '$INSTALL_ROOT/'"
  elif [ -d "$INSTALL_ROOT/.git" ]; then
    run "git -C '$INSTALL_ROOT' fetch --depth 1 origin '$BRANCH' && git -C '$INSTALL_ROOT' reset --hard 'origin/$BRANCH'"
  else
    run "git clone --depth 1 -b '$BRANCH' '$REPO_URL' '$INSTALL_ROOT'"
  fi
  ok "MagicBridgeV2 tree in $INSTALL_ROOT"
}

# =====================================================================
#  Phase 2 — dependencies (add-on layer only; kvmd already present)
# =====================================================================
phase2_deps() {
  say "Phase 2 — add-on dependencies"
  # PiKVM's system python already ships aiohttp + pyyaml (kvmd uses them) and has
  # NO pip. So only attempt an install if a dep is genuinely missing AND pip exists.
  if python3 -c "import aiohttp, yaml" 2>/dev/null; then
    ok "dependencies already present (aiohttp, pyyaml)"
  elif python3 -m pip --version >/dev/null 2>&1; then
    run "python3 -m pip install --quiet --break-system-packages -r '$INSTALL_ROOT/services/requirements.txt' || true"
    ok "dependencies installed via pip"
  else
    warn "some deps missing and pip unavailable — services may need manual deps"
  fi
}

# =====================================================================
#  Phase 3 — REBRAND the OS into MagicBridgeV2
# =====================================================================
phase3_rebrand() {
  say "Phase 3 — rebrand → MagicBridgeV2"
  # shellcheck disable=SC1091
  source "$INSTALL_ROOT/branding/branding.env"
  # hostname + mDNS
  run "hostnamectl set-hostname '${MB_HOSTNAME}' || true"
  run "install -Dm755 '$INSTALL_ROOT/branding/mb-mdns-alias.sh' /usr/local/bin/mb-mdns-alias.sh"
  run "install -Dm644 '$INSTALL_ROOT/systemd/mb-mdns-alias.service' /etc/systemd/system/mb-mdns-alias.service"
  # OLED splash + web UI branding are applied by the branding applier
  run "python3 '$INSTALL_ROOT/branding/apply_branding.py' --root '$INSTALL_ROOT'"
  # MOTD / SSH banner
  run "cp -f '$INSTALL_ROOT/branding/motd' /etc/motd || true"
  ok "OS rebranded (hostname=${MB_HOSTNAME}, OLED + UI themed)"
}

# =====================================================================
#  Phase 4 — install MagicBridgeV2 add-on services
# =====================================================================
phase4_services() {
  say "Phase 4 — install add-on services"
  # writable runtime state (survives read-only rootfs) + install-default config dir
  run "mkdir -p /var/lib/magicbridge /etc/magicbridge"
  run "chmod 700 /var/lib/magicbridge"
  if [ ! -f /etc/magicbridge/kvmd.json ] && [ "$DRY_RUN" = 0 ]; then
    # kvmd API creds used by our sidecars. Defaults match a fresh PiKVM install;
    # edit this file if you change the kvmd/web password.
    printf '{\n  "user": "admin",\n  "passwd": "admin",\n  "base": "https://127.0.0.1/api"\n}\n' > /etc/magicbridge/kvmd.json
    chmod 600 /etc/magicbridge/kvmd.json
  fi
  for unit in "$INSTALL_ROOT"/systemd/*.service; do
    [ -e "$unit" ] || continue
    run "install -Dm644 '$unit' \"/etc/systemd/system/$(basename "$unit")\""
  done
  run "systemctl daemon-reload"
  ok "services + units installed"
}

# =====================================================================
#  Phase 5 — wire nginx + kvmd overrides
# =====================================================================
phase5_wire() {
  say "Phase 5 — wire nginx + kvmd overrides"
  # our extra location blocks (served by kvmd's OWN nginx, not the stock /etc/nginx)
  run "install -Dm644 '$INSTALL_ROOT/nginx/magicbridge.conf' /etc/kvmd/nginx/magicbridge.conf"
  # kvmd override.d — our defaults, without editing kvmd's files
  run "install -Dm644 '$INSTALL_ROOT/kvmd-overrides/override.d/00-magicbridge.yaml' /etc/kvmd/override.d/00-magicbridge.yaml"
  # PiKVM builds its nginx config from a Mako template. Include our block inside the
  # HTTPS (:443) server, right after the ssl.conf include. Do NOT run `nginx -t` on
  # the stock /etc/nginx.conf — it fails on PiKVM (missing /var/log/nginx paths).
  local mako=/etc/kvmd/nginx/nginx.conf.mako
  if [ -f "$mako" ] && ! grep -q 'magicbridge.conf' "$mako"; then
    run "sed -i '/nginx\\/ssl\\.conf;/a include /etc/kvmd/nginx/magicbridge.conf;' '$mako'"
  fi
  # kvmd-nginx regenerates + validates its config on restart — that's the correct gate
  run "systemctl restart kvmd-nginx || true"
  ok "nginx wired into kvmd Mako template + kvmd-nginx restarted"
}

# =====================================================================
#  Phase 6 — enable & start
# =====================================================================
phase6_enable() {
  say "Phase 6 — enable MagicBridgeV2"
  # mDNS so magicbridge.local resolves (PiKVM ships avahi masked/off by default)
  run "systemctl unmask avahi-daemon.service avahi-daemon.socket 2>/dev/null || true"
  run "systemctl enable --now avahi-daemon.service 2>/dev/null || true"
  run "systemctl enable --now mb-mdns-alias.service || true"
  for svc in magicbridge-net magicbridge-stealth magicbridge-agent; do
    [ -f "/etc/systemd/system/${svc}.service" ] && run "systemctl enable --now '${svc}.service' || true"
  done
  run "systemctl try-restart kvmd || true"
  run "systemctl restart kvmd-oled 2>/dev/null || true"
  ok "MagicBridgeV2 enabled"
}

# =====================================================================
main() {
  banner
  phase0_preflight
  phase1_fetch
  phase2_deps
  phase3_rebrand
  phase4_services
  phase5_wire
  phase6_enable
  fs_ro
  echo
  ok "MagicBridgeV2 install complete."
  say "Open:  https://${MB_HOSTNAME:-magicbridge}.local/"
  if [ "$UPDATE" = 0 ] && [ "$DO_REBOOT" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    say "Rebooting in 5s to finalise branding (Ctrl-C to skip)…"; sleep 5; reboot
  else
    say "Done. Reboot recommended to finalise OLED/hostname."
  fi
}
main "$@"
