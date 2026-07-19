#!/usr/bin/env bash
# =====================================================================
#  MagicBridge — the one magic command
#  Turns a stock PiKVM OS install into a fully-branded MagicBridge unit.
#
#  Usage (on the V4 Mini, after flashing official PiKVM OS + first boot):
#     curl -fsSL https://raw.githubusercontent.com/razzrohith/magicbridge-pikvm/main/magic-install.sh | sudo bash
#  or, from a local clone:
#     sudo ./magic-install.sh [--branch main] [--no-reboot] [--update] [--check] [--dry-run]
#
#  Safe & idempotent: re-running upgrades in place. Reverts with ./uninstall.sh
#  Requires: PiKVM OS (Arch Linux ARM) with kvmd. Refuses to run elsewhere.
# =====================================================================
set -Eeuo pipefail

# ---- constants ------------------------------------------------------
REPO_URL="https://github.com/razzrohith/magicbridge-pikvm.git"
RAW_URL="https://raw.githubusercontent.com/razzrohith/magicbridge-pikvm"
INSTALL_ROOT="/opt/magicbridge"
BRANCH="main"
DO_REBOOT=1
DRY_RUN=0
UPDATE=0
CHECK=0
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
   __  __             _      ____       _     _
  |  \/  | __ _  __ _(_) ___| __ ) _ __(_) __| | __ _  ___
  | |\/| |/ _` |/ _` | |/ __|  _ \| '__| |/ _` |/ _` |/ _ \
  | |  | | (_| | (_| | | (__| |_) | |  | | (_| | (_| |  __/
  |_|  |_|\__,_|\__, |_|\___|____/|_|  |_|\__,_|\__, |\___|
               |___/                           |___/
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
    --check) CHECK=1; shift;;
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
  # Must be PiKVM OS with kvmd. This is the whole premise of MagicBridge PiKVM.
  if ! command -v kvmd >/dev/null 2>&1 && [ ! -d /etc/kvmd ]; then
    die "kvmd not found. MagicBridge installs on top of the official PiKVM OS.
        Flash the PiKVM OS image first, boot once, then re-run this."
  fi
  # detect read-only rootfs
  if findmnt -no OPTIONS / | grep -qw ro; then FS_WAS_RO=1; say "read-only rootfs detected — will toggle rw during install"; fi
  ok "PiKVM OS + kvmd detected"
}

# =====================================================================
#  Phase 1 — fetch MagicBridge into place
# =====================================================================
phase1_fetch() {
  say "Phase 1 — fetch MagicBridge ($BRANCH)"
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
  ok "MagicBridge tree in $INSTALL_ROOT"
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
#  Phase 3 — REBRAND the OS into MagicBridge
# =====================================================================
phase3_rebrand() {
  say "Phase 3 — rebrand → MagicBridge"
  # shellcheck disable=SC1091
  source "$INSTALL_ROOT/branding/branding.env"
  # hostname + mDNS
  run "hostnamectl set-hostname '${MB_HOSTNAME}' || true"
  run "install -Dm755 '$INSTALL_ROOT/branding/mb-mdns-alias.sh' /usr/local/bin/mb-mdns-alias.sh"
  run "install -Dm755 '$INSTALL_ROOT/provision/mb-oled-msg' /usr/local/bin/mb-oled-msg"
  run "install -Dm644 '$INSTALL_ROOT/systemd/mb-mdns-alias.service' /etc/systemd/system/mb-mdns-alias.service"
  # OLED splash + web UI branding are applied by the branding applier
  run "python3 '$INSTALL_ROOT/branding/apply_branding.py' --root '$INSTALL_ROOT'"
  # Branded login page. It lives in kvmd's web dir (/usr/share/kvmd/web/login),
  # OUTSIDE the git tree, so a fresh flash or a kvmd update would otherwise revert
  # it to the stock PiKVM login (re-showing the 2FA field, no MagicBridge brand).
  # Deploying it here makes a clean install reproduce our login exactly.
  run "install -Dm644 '$INSTALL_ROOT/web/login_index.html' /usr/share/kvmd/web/login/index.html"
  # MOTD / SSH banner
  run "cp -f '$INSTALL_ROOT/branding/motd' /etc/motd || true"
  ok "OS rebranded (hostname=${MB_HOSTNAME}, OLED + UI + login themed)"
}

# =====================================================================
#  Phase 4 — install MagicBridge add-on services
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
  say "Phase 6 — enable MagicBridge"
  # mDNS so magicbridge.local resolves (PiKVM ships avahi masked/off by default)
  run "systemctl unmask avahi-daemon.service avahi-daemon.socket 2>/dev/null || true"
  run "systemctl enable --now avahi-daemon.service 2>/dev/null || true"
  run "systemctl enable --now mb-mdns-alias.service || true"
  for svc in magicbridge-net magicbridge-stealth magicbridge-agent; do
    [ -f "/etc/systemd/system/${svc}.service" ] && run "systemctl enable --now '${svc}.service' || true"
  done
  # WiFi provisioning captive portal — raises a setup AP only when the device
  # boots with no network. Enabled (runs at boot) but NOT started now, so it
  # never disrupts the current connection.
  run "chmod +x '$INSTALL_ROOT/provision/mb-portal.sh' 2>/dev/null || true"
  run "pacman -Sy --noconfirm --needed hostapd dnsmasq 2>/dev/null || true"
  [ -f /etc/systemd/system/mb-portal.service ] && run "systemctl enable mb-portal.service 2>/dev/null || true"
  # First-boot finalize (OLED "please wait" → unique keys/id → clean state → WiFi
  # onboarding). Enable it, but drop the "done" marker NOW so a DIRECT install
  # never wipes this device on next boot. The image-prep step (docs/IMAGING.md)
  # removes the marker so ONLY a freshly-flashed golden image runs first-boot.
  run "chmod +x '$INSTALL_ROOT/provision/mb-firstboot.sh' 2>/dev/null || true"
  [ -f /etc/systemd/system/mb-firstboot.service ] && run "systemctl enable mb-firstboot.service 2>/dev/null || true"
  run "mkdir -p /var/lib/magicbridge && touch /var/lib/magicbridge/.mb-firstboot-done"
  run "systemctl try-restart kvmd || true"
  run "systemctl restart kvmd-oled 2>/dev/null || true"
  ok "MagicBridge enabled"
}

# =====================================================================
#  Doctor — read-only status report (--check). No writes, no deploy.
# =====================================================================
phase_check() {
  say "MagicBridge doctor (read-only status)"
  local okall=1
  for s in kvmd kvmd-nginx kvmd-otg magicbridge-net magicbridge-stealth magicbridge-agent; do
    if systemctl is-active --quiet "$s"; then ok "service $s active"; else warn "service $s NOT active"; okall=0; fi
  done
  [ -d "$INSTALL_ROOT/.git" ] && ok "git tree at $INSTALL_ROOT" || { warn "no git tree at $INSTALL_ROOT"; okall=0; }
  grep -q 'magicbridge.conf' /etc/kvmd/nginx/nginx.conf.mako 2>/dev/null && ok "nginx include wired" || { warn "nginx include NOT wired"; okall=0; }
  grep -q 'MagicBridge' /usr/share/kvmd/web/login/index.html 2>/dev/null && ok "branded login deployed" || warn "login page not branded (out-of-tree, SFTP it)"
  [ -f "$INSTALL_ROOT/branding/branding.env" ] && ok "branding.env present" || warn "branding.env missing"
  [ -e /var/lib/magicbridge/.mb-firstboot-done ] && ok "first-boot finalized" || warn "first-boot marker absent (would run on next boot)"
  findmnt -no OPTIONS / 2>/dev/null | grep -qw ro && ok "rootfs read-only" || warn "rootfs is RW (expected ro)"
  local ser vid
  ser=$(cat /sys/kernel/config/usb_gadget/kvmd/strings/0x409/serialnumber 2>/dev/null || true)
  if [ "$ser" = "CAFEBABE" ]; then warn "USB serial is CAFEBABE (a fake-device tell!)"; okall=0
  elif [ -n "$ser" ]; then ok "USB serial realistic ($ser)"; fi
  vid=$(cat /sys/kernel/config/usb_gadget/kvmd/idVendor 2>/dev/null || true)
  [ -n "$vid" ] && ok "USB VID=$vid (0x046d Logitech expected)"
  findmnt -no FSTYPE /var/log 2>/dev/null | grep -q tmpfs && ok "/var/log is tmpfs (RAM-only logs)" || warn "/var/log NOT tmpfs (logs may hit the SD)"
  echo
  [ "$okall" = 1 ] && ok "doctor: all green" || warn "doctor: some checks need attention (above)"
}

# =====================================================================
main() {
  banner
  phase0_preflight
  if [ "$CHECK" = 1 ]; then phase_check; fs_ro; exit 0; fi
  phase1_fetch
  phase2_deps
  phase3_rebrand
  phase4_services
  phase5_wire
  phase6_enable
  fs_ro
  echo
  ok "MagicBridge install complete."
  say "Open:  https://${MB_HOSTNAME:-magicbridge}.local/"
  if [ "$UPDATE" = 0 ] && [ "$DO_REBOOT" = 1 ] && [ "$DRY_RUN" = 0 ]; then
    say "Rebooting in 5s to finalise branding (Ctrl-C to skip)…"; sleep 5; reboot
  else
    say "Done. Reboot recommended to finalise OLED/hostname."
  fi
}
main "$@"
