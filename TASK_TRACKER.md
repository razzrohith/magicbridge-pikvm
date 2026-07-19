# ✅ MagicBridge PiKVM — Task Tracker (LIVING DOCUMENT)

> Project: **MagicBridge PiKVM** (PiKVM V4 Mini build; GitHub repo `MagicBridgeV2` for now).
> Sibling: **MagicBridge DIY** (Pi 4 + C790 + bamboo case; repo `MagicBridge`, VM CLI). V1/V2/V3 labels retired.

> **This is the single source of truth for what's done, pending, and broken.**
> Update it on EVERY change: move items between sections, add new bugs/tasks as found, and
> record each fix with its commit hash. If you're an AI assistant, keeping this current is part
> of every task — not optional.

**Last updated:** 2026-07-18
**Repo HEAD:** `75f4a92` · github.com/razzrohith/magicbridge-pikvm
**Device:** online, fully functional @ `172.16.20.209`. Pi IP changes per location.
**How to update this file:** see the "Maintenance protocol" at the bottom.

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
