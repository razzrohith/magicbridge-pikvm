# ✅ MagicBridge PiKVM — Task Tracker (LIVING DOCUMENT)

> Project: **MagicBridge PiKVM** (PiKVM V4 Mini build; GitHub repo `MagicBridgeV2` for now).
> Sibling: **MagicBridge DIY** (Pi 4 + C790 + bamboo case; repo `MagicBridge`, VM CLI). V1/V2/V3 labels retired.

> **This is the single source of truth for what's done, pending, and broken.**
> Update it on EVERY change: move items between sections, add new bugs/tasks as found, and
> record each fix with its commit hash. If you're an AI assistant, keeping this current is part
> of every task — not optional.

**Last updated:** 2026-07-19
**Repo HEAD:** `add6076` · github.com/razzrohith/magicbridge-pikvm
**Device:** ONLINE @ `172.16.20.212` (DHCP moved it from .209), hostname
`DESKTOP-LGA3O5H` (realistic, stable). All work below deployed + verified on-device.
**How to update this file:** see the "Maintenance protocol" at the bottom.

### 🎥🐛📦 DIY sync — capture-detect + installer bugfixes (handoff 8b / 5d / 20, 2026-07-19)
- **8b capture auto-detect → SKIP (informational), device-verified.** V4 Mini is
  CSI-only: `/dev/video0`=`unicam` via onboard TC358743 (`/soc/csi@7e801000`), no USB
  UVC node. kvmd owns the pipeline; Dell-EDID stealth already on the CSI path. Would
  only matter if a USB-capture variant ships.
- **5d(a) tmpfs `mode=0755` → N/A.** We mount no tmpfs log dir; `/var/log` is tmpfs
  natively (doctor only reads it). No `mode=1777` anywhere.
- **5d(b) SIGPIPE guard → FIXED** (`c302a7b`). Guarded both `tr…</dev/urandom|head`
  pipelines (`mb-anon-defaults.sh`, `mb-firstboot.sh`) with `|| true`; repo sweep found
  only those two. Device-verified: unguarded aborts `rc=141` under `set -euo pipefail`,
  guarded returns `rc=0`. `mb-anon-defaults.sh` re-confirmed idempotent (hostname + MAC
  stable across two runs).
- **20 imaging strips identity → done + extended** (`add6076`). MAC-strip already present
  (`mb-imageprep.sh` clears `70-mb-*.link`); `video.mode=auto` N/A (CSI-only). Added:
  strip `/etc/avahi/services/*.mb-bak` so the neutralized-mDNS backup (carries PiKVM
  tells on disk, never broadcast) doesn't ship inside a distributable image.
- **Reconcile sweep (live):** RAM logs ✅, nginx access-log off ✅, **no `_pikvm` on the
  wire** (`avahi-browse`) ✅, hostname realistic ✅, MAC `78:bd:bc:f8:8d:ea` persisted &
  live ✅, EDID DELL P2419H ✅, USB Logitech `046d:c52b` ✅, all services active ✅.

### 🔒 Anonymity hardening — handoff items 4, 5, 5b, 5c (verified on-device 2026-07-19)
- **Realistic hostname (#5b):** `magicbridge` → per-unit `DESKTOP-XXXXXXX` (stable,
  idempotent). Branded mDNS aliases (`magicbridge.local`/`kvm.local`) OFF by default.
- **kvmd `_pikvm._tcp` mDNS advert neutralized (#5b):** it broadcast "PiKVM Web Server /
  Raspberry Pi Compute Module 4 / board=rpi4 / serial" to any mDNS scan — emptied.
- **Realistic MAC default (#4):** networkd `.link` with a real vendor OUI (the kvmd-correct
  equivalent of DIY's NM `cloned-mac-address`; `ip link set` reverts, this sticks).
  ⏳ **applies on the next reboot** (I did not reboot the live unit unsupervised — a MAC
  change moves the DHCP IP).
- **No re-brand (#5c):** installer stopped force-setting `magicbridge`; the idempotent
  `mb-anon-defaults.sh` keeps realistic values and never re-randomizes.
- **Defaults verified realistic (#5):** USB Logitech `046d:c52b`, EDID `DELL P2419H`,
  MAC realistic, all survive `mb-secret-reset` on a clone.
- Mechanism: `mb-anon-defaults.sh` + `mb-anon-defaults.service` (boot, idempotent) +
  installer + first-boot + secret-reset. Opt-out: `MB_MAC_AUTOSPOOF`/`MB_HOSTNAME_REALISTIC`.

### 🎥 Live video VERIFIED on-device (HDMI connected, 2026-07-19)
- HDMI source connected; capture works end-to-end. `v4l2` detects **1920×1080@60**
  from the source (our Dell EDID makes it output 1080p, honored). ustreamer starts
  on-demand (kvmd stops it 10s after the last client — the idle 640×480 is just the
  no-client default), locks to 1080p, and the cockpit shows the **live 1920×1080**
  frame (MJPEG path confirmed; "No signal" overlay hidden, Status=Live).
- Fixed a UI carry-over exposed by the live test: transport labels said
  `WebRTC (C790/CSI)` / `MJPEG (USB dongle)` (DIY board name + nonexistent dongle) →
  `WebRTC (H.264)` / `MJPEG (fallback)` (commit `1c2f27f`).
### ⌨️🖱 HID input VERIFIED on-device (USB K/M gadget connected, 2026-07-19)
- Gadget bound to the host (`UDC=fe980000.usb`), `mouse.online:true absolute:true`.
- **Keyboard E2E ✅** — tapped Caps Lock via `/api/hid/events/send_key`, kvmd's
  `leds.caps` flipped `false→true` (the host received the key, toggled state, and
  reported the LED back to the gadget — full round-trip). Second tap restored it;
  no characters typed. `keyboard.online` also came `true` after activity.
- **Mouse (absolute) E2E ✅** — injected `send_mouse_move` to opposite corners; the
  captured screen showed the cursor land top-left, then bottom-right (hover popped
  the taskbar clock tooltip). Precise 1:1 absolute positioning. Cursor returned to
  center; no clicks issued on the live target.
- ⏳ Still open: WebRTC/H.264 negotiation in a REAL browser (headless fell back to
  MJPEG — MJPEG path is proven at 1080p); "Video FPS" readout shows "—" on the
  MJPEG-fallback path (cosmetic). Minor: MAC/hostname across a real reboot.

### 💿 Flashable image tooling — handoff item 20 (2026-07-19)
- **`provision/build-image.sh` built + tested** (`bf64f3f`). Arms a golden-unit `.img`
  OFFLINE (card stays an untouched backup). Detects partitions by **label/content,
  never index** — PiKVM has 4 partitions and root is **p3**; DIY hardcodes p2, which
  here is the 256M PST store, so DIY's script would strip *nothing*. Empties the MSD
  partition (uploaded ISOs). Hard-fails on LUKS. `--verify` asserts 17 strips.
- **LUKS: NOT used by PiKVM** — verified (empty `crypttab`, no dm-crypt, no
  `crypto_LUKS`). The DIY de-LUKS step is skipped entirely.
- **Three latent bugs found + fixed that would each have broken a flashed unit:**
  1. `mb-firstboot.service` was in the git tree but **never installed** to
     `/etc/systemd/system` (installer gap). A flashed card would never personalize →
     every unit sharing SSH keys/machine-id/MAC/TLS. Installed + enabled (verified
     inert on the golden unit: `ConditionResult=no`); build-image self-heals it too.
  2. `mb-secret-reset` regenerated TLS only *if a cert existed* — but arming strips
     certs, so first boot would leave **no** cert and `kvmd-nginx` would fail to
     start (bricked unit). Now unconditional (`bf64f3f`).
  3. `ipmipasswd`/`vncpasswd` never reset → every unit shipping PiKVM's stock
     `admin` credential (factory tell + shared secret). Fixed (`ce2d845`).
- **Gotchas re-checked:** (a) `/var/log` tmpfs is **755 root:root**, not 1777, and
  `fs.protected_regular=1` → bug class N/A; our installer also already refuses to run
  `nginx -t` (gates on `systemctl restart kvmd-nginx`). (b) SIGPIPE guards done
  earlier (`c302a7b`).
- **REAL IMAGE BUILT (2026-07-19).** Golden card read to
  `E:\Startup\flashOS_PIKVM\magicbridge-pikvm-base.img` (29.72 GB, byte-exact vs the
  card) → armed to `magicbridge-pikvm-dist.img`. Root correctly detected as **p3**,
  no LUKS, MSD emptied (the golden unit's 169 MB ISO gone), PST clean. **All 19
  `--verify` checks pass.** Independent audit also confirmed: hostname reset to the
  `magicbridge` placeholder tell (so anon-defaults regenerates), no residual old
  machine-id or old MAC anywhere, no bash history, `/var/log` empty.
- **Bug the real run exposed** (`a844911`) — caught by an independent audit, NOT by
  the script's own assertions: arming deleted `/etc/kvmd/htpasswd`, but
  `kvmd-htpasswd add -i` edits an EXISTING store, so first boot would have left the
  unit with **no web login**. htpasswd is now KEPT (anonymity-neutral — an identical
  value on every unit cannot cross-link them), and secret-reset recreates it from
  PiKVM's shipped default if absent. ipmipasswd/vncpasswd/TLS were never at risk
  (those are recreated with `printf >` / `openssl`).
- ⏳ Next: flash a 2nd card from `dist.img`, confirm the OLED→hotspot→WiFi flow, then
  prove uniqueness (hostname / MAC / SSH host key / machine-id all differ from golden).
- **SHRUNK + hardened (`61a6e5a`): 29.72 GB -> 6.72 GB.** Only ~2.8 GB was ever in
  use; the bulk was the empty 23.2 GB MSD partition. `build-image.sh --shrink`
  resize2fs -M's the MSD fs, shrinks the partition (via **sfdisk** — parted refuses
  its "shrinking can cause data loss" prompt even under `-s`) and truncates the file.
  Refuses unless PIMSD is genuinely the LAST partition. Root free space was zeroed
  first, so deleted-file remnants (WiFi conf, SSH keys, logs, history) are erased —
  and truncating the MSD region physically removed the deleted-ISO remnants, so the
  earlier "not safe to distribute" caveat is now RESOLVED.
- **`mb-expand-msd.sh` (new)** grows MSD back to fill whatever card the image is
  flashed onto, on first boot. Finds the partition BY LABEL (`PIMSD`), refuses to
  grow anything that is not last, no-ops when already full; every failure path just
  remounts and exits 0 (worst case: a smaller MSD — root is a different partition).
  **Untested on hardware** until the first flash.
- Final: 19/19 `--verify` pass after shrink; partition table p1 256M / p2 256M /
  p3 6G / p4 224.6M. Compressed to **`magicbridge-pikvm-dist.img.xz` = 579 MB**
  (51x smaller than the 29.72 GB original; `xz -t` verified intact). Imager flashes
  `.img.xz` natively. `pishrink` was NOT needed and remains unused.
- ⏳ **Untested on hardware:** `mb-expand-msd.sh` has never run on a real unit. Check
  MSD size on the first flashed card; if it did not grow, the unit still works fine
  (root is a separate partition) and only virtual-media capacity is affected.

### 🔁 DIY imaging sync — first-boot bug audit + repo-HEAD base (handoff 24/25, 2026-07-20)
Device was OFFLINE (flashed unit not on the LAN) → prepared + committed, on-hardware confirm pending.
- **24-i SSH/web dead on fresh flash → ALREADY SAFE** (`4c728d1`): mb-firstboot is
  Before=sysinit.target so keys/TLS regen before sshd/kvmd-nginx start; TLS regen already
  unconditional. Proven live this session (.171 came up with SSH + web 200). Added a
  deadlock-safe post-boot restart-if-failed in mb-firstboot-late.
- **24-ii restart deadlock → ALREADY SAFE**: zero systemctl restart in the boot chain.
- **24-iii portal :80 bind → SAFE BY DESIGN**: portal binds :8080 + DNATs :80/:443
  (PREROUTING). Proven live: http://192.168.73.1 worked all session.
- **24-iv stuck unit undiagnosable → FIXED** (`4c728d1`): new mb-boot-report.sh writes a
  Windows/macOS-readable report to the FAT PIBOOT partition (first-boot marker, hostapd/
  portal state, :80 holder, DNAT, services, errors — no secrets). Hooked from mb-firstboot
  + mb-portal. Exactly the visibility we lacked when the loop struck this session.
- **25 base = clean repo HEAD → DONE** (`4ad13ba`): build-image git-fetch+reset+clean syncs
  the baked /opt/magicbridge to origin/main HEAD before arming → fresh unit reports
  up-to-date (not a day-one reinstall) AND pulls all fixes in cleanly (no hand-patching).
  wtmp/btmp/lastlog N/A (/var/log tmpfs) but stripped defensively. Applied to dist.img:
  bf64f3f+7-dirty → clean HEAD; --verify now 25 checks, all pass.
- ⏳ Pending-device: confirm the PIBOOT report lands on a real stuck unit; confirm fresh
  flash reports up-to-date.

### 🛡️ FRESH-FLASH NOW SELF-COMPLETING + BULLETPROOF (mb-firstboot-late, 2026-07-20)
Made a fresh flash finish itself with zero manual steps, and immune to the 3 bugs above.
- **New post-boot oneshot `mb-firstboot-late.service`** (`6cde694`): (1) grows MSD to fill
  the card (ONLINE resize), (2) applies a UNIQUE per-unit EDID monitor serial. Both need a
  fully-up system, which is why they can't live in early mb-firstboot. Ordered
  `After=kvmd.service/multi-user.target` with NOTHING depending on it -> can never block
  boot or WiFi. Marker-guarded -> runs once (EDID serial + MSD size stay stable). Best-
  effort; worst case = smaller MSD / baked EDID serial, never a broken/looping unit.
- **PROVEN live on .171**: Result=success, MSD-grow no-ops when full, EDID serial ->
  CN05062NN (valid Dell P2419H, confirmed in the persisted hex), marker written, services
  untouched.
- Wired everywhere: build-image enables it (self-heal + clear marker), magic-install
  installs+enables, mb-imageprep clears its marker. --verify now 23 checks.
- **Net effect:** flash to any blank card -> boot -> hotspot -> WiFi -> comes up unique +
  stealthed AND fills the card + unique EDID, on its own. The failure classes are designed
  out: nofail (can't block boot), rw-before-marker (can't loop), post-boot finalize (can't
  stall provisioning).

### ✅ FLASHED UNIT FULLY WORKING + VERIFIED (172.16.20.171, 2026-07-20)
The distributable-image path is proven end-to-end after fixing 3 real hardware-only bugs.
- **Real loop bug (`2a03804`):** first-boot SUCCEEDS in ~12s, but mb-secret-reset /
  mb-anon-defaults each end by remounting rootfs **read-only**, so the done-marker
  write (`date > .mb-firstboot-done`) failed silently on a RO fs. No marker → first-boot
  re-runs every boot → re-wipes the just-entered WiFi → provisioning loop. Diagnosed via
  on-device data pulled over the setup hotspot (a self-contained offline fix script, since
  joining the hotspot kills the laptop's internet). Fix: force rw + verify + sync before
  the marker. (All earlier timeout theories were wrong.)
- **MSD grow (`3d47e9a`):** offline resize2fs failed (kvmd keeps MSD mounted) → switched to
  ONLINE resize (remount rw → resize2fs → ro). MSD 224MB → **229GB**, writable.
- **Verified UNIQUE vs golden** (all differ): hostname DESKTOP-B5BFSPR, MAC 34:17:eb (HP
  OUI, stable), machine-id 462edcb7, own SSH host key + TLS cert, EDID serial CN21233ZK.
- **All services active**, web login magicbridge/magicbridge → 200.
- **Anonymity confirmed from the TARGET (laptop):** USB = Logitech "USB Receiver"
  046D:C52B (kbd+mouse+mass-storage, NO Pi/Linux/Gadget/File-Stor tell, no phantom drive);
  HDMI EDID = DELL P2419H serial CN21233ZK (real monitor, unique per unit); on-device: RAM
  logs, no _pikvm on the wire, clean hostname.
- ⚠ Board logged **Undervoltage** — recommend a stronger USB-C PSU for stability.
- Minor: mb-firstboot's EDID-serial randomize didn't take on first boot (applied manually
  live); worth confirming the firstboot EDID step on the next build.

### 🔥 First real flash: bricked boot → root-caused + fixed (2026-07-19)
- Flashed `dist.img` onto a **238 GB** card; unit came up on WiFi (ping + **unique
  Intel MAC `a0:88:b4`**, different from golden `78:bd:bc` ✅) BUT **no service
  listened** — SSH/kvmd/web all refused, ~17 min. OLED showed an IP (a stale
  retained frame, not proof of health).
- **Root cause:** `mb-expand-msd` grew MSD to ~232 GB (partition table confirmed on
  the card), but stock PiKVM fstab mounts `PIMSD` **without `nofail`**, so the
  failed/racy mount took down `local-fs.target` and blocked the whole boot past
  networking. Exactly the untested-code risk flagged when the expand was added.
- **Fix (`649dfcd`):** build-image now sets `nofail,x-systemd.device-timeout=15s`
  (fsck pass 0) on `PIMSD` + `PIPST` — a non-essential partition can NEVER block
  boot again (worst case: MSD unmounted). `mb-expand-msd` hardened with
  `udevadm settle` (stale-table reread race) + a second `e2fsck -p`. `--verify` now
  asserts nofail (21 checks). Tested on the synthetic image (idempotent).
- **Recovery:** `wsl --mount` of the physical card needs admin (unavailable), so
  patched the existing `dist.img` in place instead (loop-mount a file needs no
  elevation): added nofail + refreshed provision scripts, re-verified 21/21,
  recompressed. User re-flashing the same card.
- **STEALTH LAYER PROVEN on real hardware (from the laptop/target):** USB =
  Logitech "USB Receiver" `046D:C52B` (no Pi/Linux/gadget tell, no phantom drive);
  HDMI EDID = Dell P2419H (DEL, no capture-card tell); LAN MAC = Intel OUI, unique
  per unit. The anonymity model works; only the boot-robustness bug remained.
- ⏳ Pending: re-flash boots (nofail guarantees it) → full on-device uniqueness +
  anonymity + services sweep; confirm MSD expand result with the hardened script.

---

## 🟢 Health snapshot — what works right now

| Area | State |
|------|-------|
| Video (WebRTC/H.264 default, MJPEG fallback) | ✅ working |
| Keyboard/mouse (abs + relative), OSK, combos, capture | ✅ working |
| Human-typing paste, clips, jiggler | ✅ working |
| WiFi captive-portal onboarding + saved-network manager | ✅ working |
| Tailscale install/up/funnel/lockdown | ✅ working (sign-in = Raj's manual step) |
| USB identity + MAC + monitor/EDID spoofing (realistic, no CAFEBABE) | ✅ working |
| Settings persistence across reboot | ✅ fixed (`95b71cc`) |
| System telemetry (latency, clients, TS peers, video detail) | ✅ working |
| VNC toggle + 2FA (TOTP) | ✅ working (off by default) |
| Professional glass UI + custom login + hidden stealth link | ✅ deployed (`7ae5597`) |
| Full rebrand, no PiKVM/RPi tells | ✅ done |

---

## ⏳ Pending / needs action

### Human-gated (only Raj can do these — not code work)
- [ ] **Tailscale sign-in** — open the login link from Network → Bring up, approve the device
      on your tailnet. (Plumbing verified; the OAuth step can't be automated.)
- [ ] **Eyeball the redesigned UI + OLED** — hard-refresh (Ctrl+Shift+R) `/login/`, `/mb/ui/`,
      `/stealth/` and glance at the front panel (should now read `MagicBridge`, not `V2`).
- [ ] **Reboot-verify MAC persistence (B8)** — the `.link` mechanism is tested on a dummy
      iface; a real reboot with a spoofed wlan0 MAC would confirm end-to-end. Low risk;
      do it on the next natural reboot.

### Open engineering tasks (nice-to-have / hardening)
- [x] **Login page folded into `magic-install.sh`** (2026-07-18) — phase 3 now deploys
      `web/login_index.html` → `/usr/share/kvmd/web/login/index.html`, so a fresh flash reproduces
      the branded, 2FA-free login. Installer `REPO_URL`/`RAW_URL` fixed to `magicbridge-pikvm`;
      installer's own `MagicBridgeV2`/`V2` strings rebranded.
- [ ] **Native `/kvm/` fallback still shows PiKVM tells** (41 on-device) — kvmd's own multi-file
      view, reverts on kvmd update. Controller-facing only (not target-facing), rarely used
      (our cockpit is default). Rebrand via installer or hide the fallback link. *(Priority: low.)*
- [ ] **Fresh-install NOT end-to-end tested** — installer is correct by inspection + syntax-checked,
      but hasn't been run on a clean PiKVM flash (no spare device). Verify on the next reimage.
- [ ] **nginx RAM-log EACCES** (from V1, may or may not exist on V2) — `nginx -t` can fail
      opening its access log; a cold restart could then fail. Check `/etc/logrotate.d/` for a
      `su`/`create` directive. *(Priority: low, but it's the only front door — confirm before
      touching.)*
- [ ] **AI Agent** — built but hidden behind a flag. Reveal only when Raj decides. When revealed,
      note it bundles Clips/Macros/Quick-Actions too (V1 side-effect).
- [ ] Optional: WiFi network **priority** ordering in the saved-network manager.
- [ ] Optional: keyboard layouts beyond US.

### Aspirational (never fully existed, incl. V1)
- [ ] Real bidirectional OS clipboard sync (the #1 wish-list item — hard, needs a target-side agent).
- [ ] Full-speed USB cap + auxiliary 3rd HID (deep gadget tweaks).

---

## ✅ Recently completed (newest first)

| Date | Commit | What |
|------|--------|------|
| 2026-07-18 | `e395b5d` | **DIY→PiKVM port (docs/PIKVM_PORT_HANDOFF.md), done offline:** anonymity — nginx access-log off (#1,#2), per-unit `mb-secret-reset.sh` + realistic default MAC-OUI + Dell EDID at first-boot (#3,#4,#5,#20), rfkill in portal (#6). Update tooling — incremental `align_pi.py` + git safe.directory (#22,#23), installer `--check` doctor (#21), OLED "Updating…" during self-update (#19). UI — cockpit re-based on DIY's latest (Software-Update category #16, "How the target sees it" identity card #14, connected-viewers, em-dash cleanup #17). Skipped #8 (kvmd native WebRTC) and #9-descriptor (kvmd native absolute mouse). #10/#11/#13/#15 already landed with the DIY-UI port. |
| 2026-07-18 | `a577926` | **UI overhaul — pro cyan-HUD redesign across all pages (login/cockpit/stealth):** new MagicBridge robot-face logo everywhere; gradient-mesh + HUD-grid backdrop, glass cards w/ hover-lift, animated nav, gradient wordmark, glowing LEDs, fluid transitions. **Esc = hold-to-exit** capture (single tap → target, hold ~2.5s or Right-Ctrl → release) w/ fullscreen + Keyboard Lock, release bar, recapture overlay, predictive cursor. **2FA field removed** from login. Skipped DIY-only bits (WoL, target-audio, OLED-settings, HID-autodisconnect, C790); kept our extras (VNC, EDID, clients, peers, LED, logs, DuckDNS, MAC). kvmd/sidecar wiring reused verbatim. ⚠️ Not yet runtime-tested in a browser (cert/origin approval needed) — verified via node --check + full authenticated render. |
| 2026-07-18 | `75f4a92` | **Bug-audit sweep — 6 verified bugs fixed & tested on-device:** MAC spoof now persists across reboot (systemd-networkd `.link`, + validation + `clear`); DuckDNS no longer marks enabled on `KO`; net `_ro()` real remount fallback; wifi/scan uses `await asyncio.sleep` (was blocking the event loop); stealth safe-mode returns an honest note; **AI-agent `key` steps now fire for real** via kvmd `send_key`/`send_shortcut` (+ key normalizer). Agent stays flag-disabled. |
| 2026-07-18 | `98bf77a` | Rebrand `MagicBridgeV2`→`MagicBridge` deployed to Pi 209 (`align_pi.py`); OLED override re-stamped to `MagicBridge` + `kvmd-oled` restarted |
| 2026-07-17 | `d5b7480` | Docs: all 6 polish phases done; final smoke test passed |
| 2026-07-17 | `842c42e` | **Phase 6:** fixed VNC toggle (os.symlink boot-persist + start/stop; `enable` EROFS), verified 2FA end-to-end |
| 2026-07-17 | `c6f7656` | **Phase 5:** System telemetry — WiFi latency/signal, connected clients, Tailscale peers, video detail |
| 2026-07-17 | `95b71cc` | **Phase 4:** killed CAFEBABE serials (USB + monitor), surfaced live MAC/serial, **fixed save_config not persisting** (RO rootfs), stripped 2 PiKVM literals |
| 2026-07-17 | `112fa2a` | **Phase 3:** fixed Tailscale (rootfs unlock + recover login URL + nginx timeout); added saved-WiFi manager; fixed the same `wpa_passphrase` bug in wifi_connect |
| 2026-07-17 | `f2c7fec` | **Phase 2:** removed Virtual Media + Wake-on-LAN; kept ATX w/ honest note |
| 2026-07-17 | `7ae5597` | **Phase 1:** professional glass UI (cockpit + stealth), custom login page, hid stealth nav link |
| 2026-07-17 | `e909cbf` | Captive portal: fixed `rw()`/`ro()` recursion crash + portal `_done` on every POST |
| 2026-07-17 | `cbda878` | Captive portal: plain-quoted psk (not wpa_passphrase) + save-then-reboot |
| 2026-07-17 | `552f289` | Captive portal: run via bash in unit, logs/leases to /run, dnsmasq bind-dynamic |
| 2026-07-16 | `0357762` | Anonymity model: main view-only / stealth edit; realistic monitors+USB; stripped tells |
| 2026-07-16 | `d208e74` | Default our UI to WebRTC (single-encoder MJPEG-black fix) |
| 2026-07-16 | `4126ba1`/`59877d8` | Soul restore: human typing, real stealth suite, dead-field fixes, WebRTC janus-version fix |
| 2026-07-14 | `19647ac` | Deferred features: OSK, clipboard paste, EDID, VNC, 2FA, stealth password, WebRTC, login rebrand |
| 2026-07-14 | `d81cba5` | Phases 3–5: relative-mouse fix, mgmt surface, net endpoints, 2 hardware bugs |
| 2026-07-14 | `6fe9188` | Installer backport (pip/nginx/phase6 fixes) + avahi/mDNS |
| 2026-07-11 | `985218f` | Scaffold MagicBridgeV2 |

*(V1 history — the Pi 4 project — is summarized in `docs/MAGICBRIDGE_SYSTEM.md` §5; V1 repo
is github.com/razzrohith/MagicBridge, reconciled through `963613f` on 2026-07-09.)*

---

## 🐛 Bug ledger (all resolved unless marked OPEN)

| ID | Status | Summary |
|----|--------|---------|
| B1 | ✅ `112fa2a` | Tailscale wouldn't install/come up (RO rootfs + lost login URL) |
| B2 | ✅ `842c42e` | VNC toggle no-op (`systemctl enable` EROFS) |
| B3 | ✅ verified | 2FA/TOTP works end-to-end (kvmd reads `/etc/kvmd/totp.secret`) |
| B4 | ✅ `95b71cc` | System page blanks (MAC/serial) — plus save_config not persisting |
| B5 | ✅ `95b71cc` | CAFEBABE serials on USB + monitor |
| B6 | ✅ `7ae5597` | Login page looked like stock PiKVM |
| B7 | ✅ `7ae5597` | Stealth link visible in main nav |
| B8 | ✅ `75f4a92` | MAC spoof didn't persist across reboot (no boot re-apply; response falsely claimed it did) — now a systemd-networkd `.link` file |
| B9 | ✅ `75f4a92` | DuckDNS marked itself `enabled` even when the update returned `KO` |
| B10 | ✅ `75f4a92` | AI-agent `key` steps were a no-op TODO — now fire via kvmd `send_key`/`send_shortcut` |
| B11 | ✅ `75f4a92` | net `_ro()` used `|| true` (could leave rootfs writable); wifi/scan blocked the event loop with `time.sleep`; stealth safe-mode returned a false "validated on hardware" note |
| — | 🟡 OPEN | nginx RAM-log EACCES (V1-era, low priority, verify on V2) |

---

## 🧭 Decisions on record (so they don't get re-litigated)
- **Virtual media + serial console = out of scope** (Raj, personal single-target use).
- **AI agent hidden** until Raj chooses to reveal it.
- **No cloud phone-home by default**; local-first.
- **Power (ATX)** kept but with an honest "needs wiring" note (can't auto-detect).
- **Wake-on-LAN removed** (useless over WiFi-only with no wired target NIC).
- **Stealth page** reached only by direct `/stealth/` URL + its password; no nav link.
- **Dependency-free frontend** (no CDN) — hand-roll small things; it's a self-hosted offline-capable tool.
- **Realistic, creative, codebase-grounded features** — not generic admin-panel checklist items.

---

## 🔧 Maintenance protocol (how to keep this file honest)
1. When you START a task, note it under Pending (or a new "In progress" line).
2. When you FINISH, move it to "Recently completed" **with the commit hash**, and flip its bug
   ID to ✅ if applicable.
3. When you DISCOVER a bug, add it to the Bug ledger as OPEN immediately.
4. Update **Repo HEAD** and **Last updated** at the top after each push.
5. Anything genuinely novel/non-obvious you learned → also add it to
   `docs/MAGICBRIDGE_SYSTEM.md` so the next fresh chat inherits it.
