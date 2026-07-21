#!/usr/bin/env bash
# ============================================================
#  build-image.sh — arm a MagicBridge PiKVM .img for distribution.
#
#  Takes a raw image read off a fully-working "golden" V4 Mini card and strips
#  every per-unit secret + identity, then RE-ARMS first-boot so each flashed
#  card personalizes itself into a unique, anonymous unit:
#      flash -> boot -> mb-firstboot (regenerate secrets) -> hotspot WiFi setup
#
#  Run on a LINUX host as root (WSL2 works; loop devices + mount are required):
#      wsl -d Ubuntu -u root -e bash /mnt/e/.../build-image.sh <base.img> [out.img]
#      wsl -d Ubuntu -u root -e bash /mnt/e/.../build-image.sh --verify <img>
#
#  ---- Why this is NOT DIY's build-image.sh -------------------------------
#  DIY = Pi OS, 2 partitions, root on p2, NetworkManager, /etc/magicbridge.
#  PiKVM V4 Mini = 4 partitions and root is p3:
#      p1 vfat  PIBOOT -> /boot
#      p2 ext4  PIPST  -> /var/lib/kvmd/pst   (kvmd persistent store)
#      p3 ext4         -> /                   <-- the real root
#      p4 ext4  PIMSD  -> /var/lib/kvmd/msd   (uploaded ISOs - must not ship)
#  Hardcoding p2 as root (as DIY does) would mount the 256M PST partition and
#  silently strip NOTHING. So we detect partitions by label/content, never by
#  index. Secrets are kvmd's (htpasswd/ipmipasswd/vncpasswd/TLS), not DIY's.
#  LUKS: PiKVM does not use it (verified: empty crypttab, no dm-crypt) - we
#  still hard-FAIL if a LUKS container ever shows up rather than silently
#  arming an image whose secrets we did not actually reach.
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; NC='\033[0m'
ok(){   echo -e "${GRN}✓${NC} $*"; }
info(){ echo -e "→ $*"; }
warn(){ echo -e "${YEL}⚠${NC} $*"; }
die(){  echo -e "${RED}✗${NC} $*"; exit 1; }

MODE="arm"
if [[ "${1:-}" == "--verify" ]]; then MODE="verify"; shift; fi
if [[ "${1:-}" == "--shrink" ]]; then MODE="shrink"; shift; fi
IMG="${1:-}"
[[ $EUID -eq 0 ]] || die "Run as root (needs loop mount)."
[[ -f "$IMG" ]]   || die "Usage: $0 <base.img> [out.img]   |   $0 --verify <img>"
command -v losetup >/dev/null || die "losetup not found (install util-linux)."

OUT="${2:-}"
if [[ "$MODE" == "arm" ]]; then
    if [[ -n "$OUT" && "$OUT" != "$IMG" ]]; then
        info "Copying $IMG -> $OUT (base image stays untouched as your backup)"
        cp --reflink=auto "$IMG" "$OUT"
    else
        OUT="$IMG"; warn "Editing $IMG IN PLACE (pass an output name to keep the base)"
    fi
else
    OUT="$IMG"
fi

if [[ "$MODE" == "shrink" ]]; then OUT="$IMG"; fi

MNT=$(mktemp -d); LOOP=""
cleanup(){
    for m in "$MNT/msd" "$MNT/pst" "$MNT/root"; do mountpoint -q "$m" && umount "$m" 2>/dev/null || true; done
    [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null || true
    rm -rf "$MNT" 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$MNT/root" "$MNT/pst" "$MNT/msd"

info "Attaching image..."
LOOP=$(losetup --show -fP "$OUT")
sleep 1   # give udev time to create the pN nodes

# ---- identify partitions by LABEL/content, never by index -----------------
ROOTPART=""; MSDPART=""; PSTPART=""; BOOTPART=""
for p in "${LOOP}"p*; do
    [[ -e "$p" ]] || continue
    # unset FIRST: the case branches below `continue`, so a stale label from the
    # previous partition would otherwise leak in and misidentify this one.
    unset BLK_LABEL BLK_TYPE
    eval "$(blkid -o export "$p" 2>/dev/null | sed 's/^/BLK_/')" || true
    lbl="${BLK_LABEL:-}"; typ="${BLK_TYPE:-}"
    case "$lbl" in
        PIBOOT) BOOTPART="$p"; continue ;;
        PIPST)  PSTPART="$p";  continue ;;
        PIMSD)  MSDPART="$p";  continue ;;
    esac
    # unlabelled ext4 -> candidate root; confirm by content
    if [[ "$typ" == "ext4" ]]; then
        if mount -o ro "$p" "$MNT/root" 2>/dev/null; then
            if [[ -d "$MNT/root/etc/kvmd" ]]; then ROOTPART="$p"; fi
            umount "$MNT/root" 2>/dev/null || true
        fi
    fi
done
[[ -n "$ROOTPART" ]] || die "Could not find the kvmd root partition (no ext4 containing /etc/kvmd). Is this a PiKVM image?"
info "root=$ROOTPART  boot=${BOOTPART:-none}  pst=${PSTPART:-none}  msd=${MSDPART:-none}"

# ---- LUKS guard (the trap that bit DIY) ----------------------------------
for p in "${LOOP}"p*; do
    [[ -e "$p" ]] || continue
    if blkid -o value -s TYPE "$p" 2>/dev/null | grep -qi crypto_LUKS; then
        die "LUKS container on $p. This image ships an encrypted store; arming it
   blindly would leave a SHARED key inside every flashed unit. De-LUKS it first
   (luksOpen with the boot-partition keyfile, copy out, delete container+keyfile
   +crypttab lines, remove the in-container firstboot flags) before re-running."
    fi
done
ok "No LUKS container (expected for PiKVM)"

# =========================================================================
#  SHRINK MODE — shrink the (empty, last) MSD partition and truncate the file
#  so the .img flashes onto any reasonably sized card. mb-expand-msd.sh grows
#  it back to the real card size on first boot.
# =========================================================================
if [[ "$MODE" == "shrink" ]]; then
    [[ -n "$MSDPART" ]] || die "no PIMSD partition to shrink"
    PNUM="${MSDPART##*p}"
    # SAFETY: only shrink if MSD really is the last partition on the disk.
    # (sysfs, not partx: `-nr` glues into one option and misparses the range.)
    msd_start=$(cat "/sys/class/block/$(basename "$MSDPART")/start")
    for p in "${LOOP}"p*; do
        [[ -e "$p" ]] || continue
        s=$(cat "/sys/class/block/$(basename "$p")/start" 2>/dev/null || echo 0)
        [[ "$s" -gt "$msd_start" ]] && die "PIMSD is not the last partition - refusing to shrink"
    done
    info "Shrinking MSD ($MSDPART) ..."
    e2fsck -f -p "$MSDPART" >/dev/null 2>&1 || true
    resize2fs -M "$MSDPART" >/dev/null 2>&1 || die "resize2fs -M failed"
    BC=$(dumpe2fs -h "$MSDPART" 2>/dev/null | awk -F: '/Block count/{gsub(/ /,"",$2);print $2}')
    BS=$(dumpe2fs -h "$MSDPART" 2>/dev/null | awk -F: '/Block size/{gsub(/ /,"",$2);print $2}')
    [[ -n "$BC" && -n "$BS" ]] || die "could not read MSD filesystem geometry"
    # keep a little slack so ext4 isn't pinned at its absolute minimum
    NEWBYTES=$(( BC * BS + 32*1024*1024 ))
    NEWSECT=$(( (NEWBYTES + 511) / 512 ))
    NEWEND=$(( msd_start + NEWSECT - 1 ))
    info "MSD fs = $((BC*BS/1024/1024)) MiB -> partition end sector $NEWEND"
    # sfdisk, not parted: parted refuses its "shrinking can cause data loss"
    # prompt even under -s, so resizepart always returns 1 here.
    echo ",${NEWSECT}" | sfdisk -N "$PNUM" --force --no-reread --no-tell-kernel "$LOOP" >/dev/null 2>&1 \
        || die "sfdisk resize of partition $PNUM failed"
    partprobe "$LOOP" 2>/dev/null || partx -u "$LOOP" 2>/dev/null; sleep 1
    resize2fs "$MSDPART" >/dev/null 2>&1 || true   # fill the slack
    sync
    losetup -d "$LOOP"; LOOP=""; trap - EXIT; rm -rf "$MNT"
    NEWSIZE=$(( (NEWEND + 1) * 512 ))
    truncate -s "$NEWSIZE" "$IMG"
    ok "Image truncated to $(( NEWSIZE/1024/1024 )) MiB ($IMG)"
    echo "  MSD grows back to the full card on first boot (mb-expand-msd.sh)."
    echo "  Next: $0 --verify $IMG   then compress:  xz -T0 -v $IMG"
    exit 0
fi

mount "$ROOTPART" "$MNT/root"
R="$MNT/root"
[[ -d "$R/opt/magicbridge" ]] || warn "No /opt/magicbridge in this image - is MagicBridge actually installed on the golden unit?"

# =========================================================================
#  VERIFY MODE — assert every strip actually took
# =========================================================================
if [[ "$MODE" == "verify" ]]; then
    FAIL=0
    chk(){ if eval "$2"; then ok "$1"; else echo -e "${RED}✗${NC} $1"; FAIL=1; fi; }
    echo ""; info "Verifying armed image: $IMG"
    chk "no SSH host keys"            '! ls "$R"/etc/ssh/ssh_host_* >/dev/null 2>&1'
    chk "machine-id empty"            '[[ ! -s "$R/etc/machine-id" ]]'
    chk "no saved WiFi (no ssid=)"    '! grep -qi "ssid=" "$R"/etc/wpa_supplicant/wpa_supplicant-wlan0.conf 2>/dev/null'
    chk "no spoofed-MAC .link"        '! ls "$R"/etc/systemd/network/70-mb-*.link >/dev/null 2>&1'
    chk "no Tailscale state"          '[[ ! -e "$R/var/lib/tailscale/tailscaled.state" ]]'
    chk "first-boot marker removed"   '[[ ! -e "$R/var/lib/magicbridge/.mb-firstboot-done" ]]'
    chk "mb-firstboot.service present" '[[ -f "$R/etc/systemd/system/mb-firstboot.service" ]]'
    chk "mb-firstboot ENABLED (sysinit)" '[[ -L "$R/etc/systemd/system/sysinit.target.wants/mb-firstboot.service" ]]'
    chk "mb-portal ENABLED (multi-user)" '[[ -L "$R/etc/systemd/system/multi-user.target.wants/mb-portal.service" ]]'
    chk "kvmd TLS stripped (nginx)"   '[[ ! -e "$R/etc/kvmd/nginx/ssl/server.key" ]]'
    chk "kvmd TLS stripped (vnc)"     '[[ ! -e "$R/etc/kvmd/vnc/ssl/server.key" ]]'
    chk "no stock admin in ipmipasswd" '! grep -qE "^admin:" "$R/etc/kvmd/ipmipasswd" 2>/dev/null'
    chk "USB serial override cleared" '[[ ! -e "$R/etc/kvmd/override.d/90-magicbridge-otg.yaml" ]]'
    chk "no avahi .mb-bak tells"      '! ls "$R"/etc/avahi/services/*.mb-bak >/dev/null 2>&1'
    chk "defaults KEPT (kvmd.json)"   '[[ -f "$R/etc/magicbridge/kvmd.json" ]]'
    chk "defaults KEPT (stealth_auth)" '[[ -f "$R/etc/magicbridge/stealth_auth.json" ]]'
    # htpasswd must SURVIVE: kvmd-htpasswd edits an existing file, so a missing one
    # can leave the flashed unit with no web login. Must also not carry stock 'admin'.
    chk "htpasswd KEPT (unit stays loginable)" '[[ -s "$R/etc/kvmd/htpasswd" ]]'
    chk "htpasswd has no stock admin user"     '! cut -d: -f1 "$R/etc/kvmd/htpasswd" 2>/dev/null | grep -qx admin'
    chk "PIMSD mount is nofail (cannot block boot)" 'grep -qE "LABEL=PIMSD.*nofail" "$R/etc/fstab"'
    chk "PIPST mount is nofail (cannot block boot)" 'grep -qE "LABEL=PIPST.*nofail" "$R/etc/fstab"'
    chk "mb-firstboot-late ENABLED (MSD grow + EDID)" '[[ -L "$R/etc/systemd/system/multi-user.target.wants/mb-firstboot-late.service" ]]'
    chk "mb-firstboot-late marker cleared"           '[[ ! -e "$R/var/lib/magicbridge/.mb-firstboot-late-done" ]]'
    git config --global --add safe.directory "$R/opt/magicbridge" 2>/dev/null || true
    chk "baked repo tree is CLEAN (item 25: up-to-date)" '[[ -z "$(git -C "$R/opt/magicbridge" status --short 2>/dev/null)" ]]'
    chk "no wtmp/btmp login history shipped"          '! ls "$R"/var/log/wtmp "$R"/var/log/btmp >/dev/null 2>&1'
    # item 27: assert the specific VALUES that matter, not just "file exists" —
    # every installed unit must byte-match the repo, and the fixes must be present.
    chk "installed units all match repo (no stale .service)" 'for u in "$R"/opt/magicbridge/systemd/*.service; do cmp -s "$u" "$R/etc/systemd/system/$(basename "$u")" || exit 1; done'
    chk "mb-portal timeout NOT capped (26e: no mid-setup kill)" 'grep -qE "TimeoutStartSec=(infinity|0)\b" "$R/etc/systemd/system/mb-portal.service"'
    chk "wifi save REPLACES bad creds (26b: no stranding)" 'grep -q "REPLACE, never blind-append" "$R/opt/magicbridge/provision/mb-portal.sh"'
    if [[ -n "$MSDPART" ]]; then
        mount "$MSDPART" "$MNT/msd" 2>/dev/null || true
        chk "MSD has no uploaded images" '[[ -z "$(find "$MNT/msd" -maxdepth 1 -type f ! -name ".*" 2>/dev/null)" ]]'
    fi
    echo ""
    [[ $FAIL -eq 0 ]] && ok "ALL CHECKS PASSED — image is safe to distribute" \
                      || die "Some checks FAILED — do not distribute this image"
    exit 0
fi

# =========================================================================
#  ARM MODE
# =========================================================================
info "Stripping per-unit identity + secrets..."

# 0. ITEM 25: ship the baked repo at CLEAN origin/main HEAD. Otherwise a fresh
#    unit reports "N commits behind" and does a pointless day-one full reinstall
#    (the golden card was snapshotted at whatever commit it happened to be on, and
#    any in-image patching leaves the tree dirty). Syncing to HEAD also pulls in
#    every committed fix cleanly, so we no longer hand-patch scripts into the image.
#    Runs BEFORE the first-boot re-arm below, which reads systemd units from the tree.
if git -C "$R/opt/magicbridge" rev-parse >/dev/null 2>&1; then
    git config --global --add safe.directory "$R/opt/magicbridge" 2>/dev/null || true
    if git -C "$R/opt/magicbridge" fetch origin main -q 2>/dev/null; then
        git -C "$R/opt/magicbridge" reset --hard origin/main -q 2>/dev/null
    else
        warn "no network to fetch origin - baked repo stays at its current commit ($(git -C "$R/opt/magicbridge" rev-parse --short HEAD 2>/dev/null))"
        git -C "$R/opt/magicbridge" reset --hard HEAD -q 2>/dev/null   # at least make it clean
    fi
    git -C "$R/opt/magicbridge" clean -fdq 2>/dev/null   # drop __pycache__ + stray files
    ok "baked repo at clean HEAD $(git -C "$R/opt/magicbridge" rev-parse --short HEAD 2>/dev/null) (fresh unit reports up-to-date)"
else
    warn "no git tree at /opt/magicbridge in the image - skipping repo-HEAD sync"
fi
# ITEM 27: re-deploy EVERY unit file from the (now-HEAD) repo, overwriting stale
# installed copies. The image is snapshotted from a golden unit whose
# /etc/systemd/system units are frozen at INSTALL time — a later fix to a .service
# (e.g. mb-portal's TimeoutStartSec) lands in /opt/magicbridge but NOT in the
# installed unit, so half a fix ships. Proven: the built image carried
# mb-portal.service with the OLD 1200s timeout while the repo had infinity.
if [[ -d "$R/opt/magicbridge/systemd" ]]; then
    _n=0
    for u in "$R/opt/magicbridge/systemd"/*.service; do
        [[ -e "$u" ]] || continue
        install -Dm644 "$u" "$R/etc/systemd/system/$(basename "$u")"; _n=$((_n+1))
    done
    ok "re-deployed all $_n repo unit files (item 27: no stale .service ships)"
fi
# wtmp/btmp/lastlog: on PiKVM /var/log is tmpfs so these never persist to the card,
# but strip any on-disk copies defensively (login/reboot history cross-links units).
rm -f "$R"/var/log/wtmp* "$R"/var/log/btmp* "$R"/var/log/lastlog 2>/dev/null || true

# 1. Host identity
rm -f "$R"/etc/ssh/ssh_host_* 2>/dev/null || true
rm -f "$R/var/lib/dbus/machine-id" 2>/dev/null || true
: > "$R/etc/machine-id"

# 2. kvmd credentials. ipmipasswd/vncpasswd are safe to delete: mb-secret-reset
#    rewrites them with `printf >`, which creates the file.
#    htpasswd is DELIBERATELY KEPT. mb-secret-reset re-seeds it via
#    `kvmd-htpasswd add -i`, and that tool operates on an EXISTING file - delete it
#    and a flashed unit can end up with no web login at all. Keeping it is also
#    anonymity-neutral: it holds only the documented default user (magicbridge), and
#    a value identical on every unit cannot cross-link units (that needs a UNIQUE
#    value). Same rationale as kvmd.json / stealth_auth.json below. First boot
#    normalizes it back to the default anyway, so a custom builder password
#    does not survive into flashed units.
rm -f "$R/etc/kvmd/ipmipasswd" "$R/etc/kvmd/vncpasswd" 2>/dev/null || true
: > "$R/etc/kvmd/totp.secret" 2>/dev/null || true

# 3. kvmd TLS — stock certs are IDENTICAL across every install of an OS build,
#    and a clone would share them. mb-secret-reset regenerates unconditionally.
rm -f "$R"/etc/kvmd/nginx/ssl/server.* "$R"/etc/kvmd/vnc/ssl/server.* 2>/dev/null || true

# 4. Network identity: saved WiFi, spoofed MAC, Tailscale node.
printf 'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n' \
    > "$R/etc/wpa_supplicant/wpa_supplicant-wlan0.conf" 2>/dev/null || true
rm -f "$R"/etc/systemd/network/70-mb-*.link 2>/dev/null || true
rm -f "$R/var/lib/tailscale/tailscaled.state" 2>/dev/null || true

# 5. Our per-unit runtime state + USB serial override (regenerated per unit).
rm -f "$R"/var/lib/magicbridge/net.json "$R"/var/lib/magicbridge/stealth.json \
      "$R"/var/lib/magicbridge/stealth_auth.json "$R"/var/lib/magicbridge/agent.json 2>/dev/null || true
rm -f "$R/etc/kvmd/override.d/90-magicbridge-otg.yaml" 2>/dev/null || true
# Residual mDNS tells: our neutralization leaves a pikvm.service.mb-bak backup
# that avahi never broadcasts but which still carries PiKVM strings on disk.
rm -f "$R"/etc/avahi/services/*.mb-bak 2>/dev/null || true

# 6. Hostname back to a placeholder TELL so mb-anon-defaults regenerates a fresh
#    realistic DESKTOP-XXXXXXX per unit (it only replaces a known tell).
printf 'magicbridge\n' > "$R/etc/hostname" 2>/dev/null || true

# 7. Logs / history — nothing personal ships.
rm -rf "$R"/var/log/* 2>/dev/null || true
rm -f  "$R/root/.bash_history" 2>/dev/null || true

# 8. RE-ARM first boot: drop the marker + make sure the service is installed AND
#    enabled in the RIGHT target. mb-firstboot is WantedBy=sysinit.target (NOT
#    multi-user like DIY's) - wrong target = personalization silently never runs.
rm -f "$R/var/lib/magicbridge/.mb-firstboot-done" 2>/dev/null || true
mkdir -p "$R/var/lib/magicbridge" 2>/dev/null || true; chmod 700 "$R/var/lib/magicbridge" 2>/dev/null || true
# Self-heal the known installer gap: unit present in the git tree but never
# installed to /etc/systemd/system.
if [[ ! -f "$R/etc/systemd/system/mb-firstboot.service" && -f "$R/opt/magicbridge/systemd/mb-firstboot.service" ]]; then
    install -Dm644 "$R/opt/magicbridge/systemd/mb-firstboot.service" \
                   "$R/etc/systemd/system/mb-firstboot.service"
    warn "mb-firstboot.service was missing from the image - installed it from the tree"
fi
if [[ -f "$R/etc/systemd/system/mb-firstboot.service" ]]; then
    mkdir -p "$R/etc/systemd/system/sysinit.target.wants"
    ln -sf ../mb-firstboot.service "$R/etc/systemd/system/sysinit.target.wants/mb-firstboot.service"
    ok "mb-firstboot enabled (sysinit.target)"
else
    die "mb-firstboot.service missing and not in the tree - the flashed unit would NEVER personalize."
fi
if [[ -f "$R/etc/systemd/system/mb-portal.service" ]]; then
    mkdir -p "$R/etc/systemd/system/multi-user.target.wants"
    ln -sf ../mb-portal.service "$R/etc/systemd/system/multi-user.target.wants/mb-portal.service"
    ok "mb-portal enabled (multi-user.target) - hotspot comes up when there's no WiFi"
else
    warn "mb-portal.service missing - a flashed unit will have no WiFi onboarding hotspot"
fi
# mb-firstboot-late: post-boot, one-time MSD-grow + unique-EDID-serial. Self-heal
# it from the tree (installer-gap safe), enable it, and clear its marker so a
# flashed unit re-runs it. It runs AFTER boot, so it can never block boot/WiFi.
rm -f "$R/var/lib/magicbridge/.mb-firstboot-late-done" 2>/dev/null || true
if [[ ! -f "$R/etc/systemd/system/mb-firstboot-late.service" && -f "$R/opt/magicbridge/systemd/mb-firstboot-late.service" ]]; then
    install -Dm644 "$R/opt/magicbridge/systemd/mb-firstboot-late.service" \
                   "$R/etc/systemd/system/mb-firstboot-late.service"
fi
if [[ -f "$R/etc/systemd/system/mb-firstboot-late.service" ]]; then
    mkdir -p "$R/etc/systemd/system/multi-user.target.wants"
    ln -sf ../mb-firstboot-late.service "$R/etc/systemd/system/multi-user.target.wants/mb-firstboot-late.service"
    ok "mb-firstboot-late enabled (post-boot MSD grow + unique EDID)"
else
    warn "mb-firstboot-late.service missing - MSD won't auto-grow (harmless: run mb-expand-msd.sh later)"
fi
ok "Root partition stripped + first boot re-armed"

# 8b. CRITICAL robustness: make the virtual-media (PIMSD) and kvmd-persistent
#     (PIPST) mounts `nofail`. Stock PiKVM fstab has neither, so a single failed
#     mount of a NON-essential partition takes down local-fs.target and blocks the
#     whole boot - no SSH, no kvmd, no web (exactly what bricked the first flashed
#     unit after the MSD resize). With nofail, worst case the unit boots normally
#     with MSD simply unmounted. Idempotent (skips if nofail already present).
if [[ -f "$R/etc/fstab" ]]; then
    python3 - "$R/etc/fstab" <<'PY' 2>/dev/null || \
    sed -i -E '/LABEL=(PIMSD|PIPST)/ { /nofail/! s/errors=remount-ro/errors=remount-ro,nofail,x-systemd.device-timeout=15s/ }' "$R/etc/fstab"
import sys,re
p=sys.argv[1]; out=[]
for ln in open(p):
    if re.search(r'LABEL=(PIMSD|PIPST)', ln) and 'nofail' not in ln:
        cols=ln.split()
        if len(cols)>=6:
            opts=cols[3].split(',')
            opts += ['nofail','x-systemd.device-timeout=15s']
            cols[3]=','.join(opts); cols[5]='0'   # fsck pass 0: never block boot on fsck either
            ln='  '.join(cols)+'\n'
    out.append(ln)
open(p,'w').writelines(out)
PY
    ok "PIMSD + PIPST mounts made nofail (a bad virtual-media partition can no longer block boot)"
fi

# 9. MSD partition: the golden unit's uploaded ISO images. Large + personal;
#    never ship them. (kvmd-specific; DIY has no equivalent.)
if [[ -n "$MSDPART" ]]; then
    mount "$MSDPART" "$MNT/msd"
    find "$MNT/msd" -mindepth 1 -maxdepth 1 ! -name 'lost+found' -exec rm -rf {} + 2>/dev/null || true
    sync; umount "$MNT/msd"
    ok "MSD partition emptied (no uploaded ISOs ship)"
fi

# 10. PST partition: kvmd's persistent store. Normally empty; warn if not.
if [[ -n "$PSTPART" ]]; then
    mount "$PSTPART" "$MNT/pst" 2>/dev/null || true
    if [[ -n "$(find "$MNT/pst/data" -mindepth 1 2>/dev/null)" ]]; then
        warn "PST (kvmd persistent store) is NOT empty - inspect it before shipping"
    else
        ok "PST partition clean"
    fi
    umount "$MNT/pst" 2>/dev/null || true
fi

sync
umount "$MNT/root"; losetup -d "$LOOP"; LOOP=""; trap - EXIT; rm -rf "$MNT"

echo ""
ok "Armed image ready: $OUT"
echo "  Verify it:  $0 --verify $OUT"
echo "  Shrink it:  pishrink.sh $OUT      (see docs/IMAGING.md for the caveat)"
echo "  Flash it:   Raspberry Pi Imager -> 'Use custom' -> $OUT (skip OS customization)"
echo "  First boot: OLED 'please wait' -> hotspot 'MagicBridge-Setup' -> enter WiFi."
