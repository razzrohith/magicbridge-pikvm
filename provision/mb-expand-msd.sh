#!/usr/bin/env bash
# ============================================================
#  mb-expand-msd.sh — grow the virtual-media (MSD) partition to fill the card.
#
#  A distributable image is built with the MSD partition SHRUNK to almost nothing
#  (it is the last partition and normally empty, so shrinking it takes the .img
#  from ~30GB to ~6.5GB and lets it flash onto any card >=8GB). This grows it back
#  to whatever the actual card can hold, on the first boot of a flashed unit.
#
#  Called by mb-firstboot.sh. Safe to run any time and on a NON-shrunk unit: it
#  no-ops when the partition already reaches the end of the disk.
#
#  Failure is deliberately BENIGN — every error path just remounts and exits 0.
#  Worst case the unit boots with a small MSD (less virtual-media room); the OS
#  itself is untouched because root is a different, earlier partition.
# ============================================================
set +e
log(){ echo "[$(date)] expand-msd: $*"; }

MP=/var/lib/kvmd/msd

# Locate the MSD partition BY LABEL (never hardcode p4 - the label survives both
# the shrink and the grow, and is what fstab mounts).
MSDDEV="$(blkid -L PIMSD 2>/dev/null)"
[ -b "$MSDDEV" ] || { log "no PIMSD partition found - nothing to do"; exit 0; }

PNAME="$(basename "$MSDDEV")"
DNAME="$(lsblk -no pkname "$MSDDEV" 2>/dev/null | head -1)"
[ -n "$DNAME" ] || { log "cannot resolve parent disk of $MSDDEV - skipping"; exit 0; }
DISK="/dev/$DNAME"
PARTNUM="$(cat "/sys/class/block/$PNAME/partition" 2>/dev/null)"
[ -n "$PARTNUM" ] || { log "cannot resolve partition number - skipping"; exit 0; }

# SAFETY: only ever grow the LAST partition. Growing one that has another
# partition after it would overwrite that partition's data.
msd_start="$(cat "/sys/class/block/$PNAME/start" 2>/dev/null || echo 0)"
for s in /sys/class/block/"$DNAME"*/start; do
    [ -e "$s" ] || continue
    other="$(cat "$s" 2>/dev/null || echo 0)"
    if [ "$other" -gt "$msd_start" ]; then
        log "PIMSD is NOT the last partition (something starts at $other) - refusing to grow"
        exit 0
    fi
done

# Is there actually meaningful unallocated space after it? (<64MiB slack = done)
disk_sz="$(blockdev --getsz "$DISK" 2>/dev/null || echo 0)"
part_sz="$(blockdev --getsz "$MSDDEV" 2>/dev/null || echo 0)"
free=$(( disk_sz - msd_start - part_sz ))
if [ "$free" -lt 131072 ]; then
    log "already fills the card (${free} spare sectors) - nothing to do"
    exit 0
fi
log "growing $MSDDEV (partition $PARTNUM on $DISK), ${free} sectors free"

# Grow the LAST partition (safe: nothing after it to overwrite). Do NOT --no-tell-
# kernel here: we want the kernel to pick up the new size for the mounted last
# partition (BLKPG). sfdisk is deterministic; parted is a fallback.
newsize=$(( disk_sz - msd_start ))
if ! echo ",${newsize}" | sfdisk -N "$PARTNUM" --force "$DISK" >/dev/null 2>&1; then
    log "sfdisk grow failed - trying parted"
    parted -s -f "$DISK" resizepart "$PARTNUM" 100% >/dev/null 2>&1 || \
        { log "resizepart failed - leaving MSD as-is"; exit 0; }
fi
partprobe "$DISK" 2>/dev/null || partx -u "$DISK" 2>/dev/null
udevadm settle --timeout=10 2>/dev/null
sleep 1

# Grow the filesystem ONLINE. kvmd keeps MSD mounted (ro), so an unmount is
# unreliable (device busy) and an offline resize then fails - which is exactly
# what left MSD un-grown on the first real unit. ext4 online-grow works fine on a
# mounted fs; we only need it rw for the resize, then restore the ro that kvmd
# expects. No forced fsck (slow on a huge fs, and a mounted fs can't be fsck'd).
was_ro=""; mount | grep -q " $MP .*[(,]ro[,)]" && was_ro=1
mount -o remount,rw "$MP" 2>/dev/null
if resize2fs "$MSDDEV" >/dev/null 2>&1; then
    log "MSD grown to $(blockdev --getsize64 "$MSDDEV" 2>/dev/null) bytes"
else
    log "resize2fs failed - MSD stays at its current size (boot is safe: nofail)"
fi
# Restore the read-only mount kvmd expects (only if it was ro to begin with).
[ -n "$was_ro" ] && mount -o remount,ro "$MP" 2>/dev/null
exit 0
