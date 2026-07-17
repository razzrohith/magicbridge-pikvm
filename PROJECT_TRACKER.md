# MagicBridgeV2 — Project Tracker & Roadmap

> Living document. Every bug, task, feature, decision and fix lives here.
> Update it on every change: move items between **Pending → In progress → Done**,
> add new bugs as found, and record fixes in the Changelog with the commit hash.

**Last updated:** 2026-07-17
**Device state:** Online — joined WiFi "Quality Inn- Office" @ 192.168.1.37, reachable at `http://magicbridge.local/`
**Repo:** github.com/razzrohith/MagicBridgeV2 · HEAD `e909cbf`
**Hard constraints:** dependency-free frontend (no CDN), never expose PiKVM / Raspberry Pi / kvmd / capture-card tells, main page = view-only identity / edit only in Stealth, realistic keyboard+mouse+monitor values only.

---

## 1. Snapshot — what works today

| Area | Status |
|------|--------|
| WiFi captive-portal provisioning (new-site setup) | ✅ Fixed & live (see Changelog) |
| Screen / video (WebRTC H.264 default, MJPEG fallback) | ✅ Working |
| Relative + absolute mouse, human-typing paste, OSK, clips, combos | ✅ Working |
| Click-to-capture / Esc-to-release | ✅ Working |
| Branding (MagicBridgeV2, PiKVM tells stripped from visible UI) | ✅ Mostly — see B5 |
| Professional glass UI theme (cockpit + Stealth page) + custom login page | ✅ Deployed `7ae5597` — awaiting Raj's visual confirmation (Chrome extension was offline this session) |
| Stealth page hidden from main nav / no mention in main UI | ✅ Done `7ae5597` |
| USB identity presets + MAC spoof + monitor(EDID) spoof (Stealth page) | ⚠️ Present but not fully verified/applied (Phase 4) |
| Power (ATX) / Virtual Media / Wake-on-LAN pages | ✅ Cleaned up `[pending commit]` — MSD + WoL removed, ATX kept w/ honest "not wired" note (see D1 revision below) |
| Tailscale install / bring-up / Funnel | ✅ Fixed `[pending commit]` — see B1 resolution below |
| Saved-WiFi management (list/add/forget) in UI | ✅ Done `[pending commit]` — Network page now lists saved SSIDs with Forget |
| VNC remote access | ❌ Not working (B2) |
| Two-factor (TOTP) login | ❌ Not working (B3) |
| Saved-WiFi management (list/edit/forget) in UI | ❌ Missing (Phase 3) |
| UI theme (professional/glassy) & login page distinct from PiKVM | ❌ Redesign needed (Phase 1) |

---

## 2. Open bugs

- **B1 — Tailscale won't install or come up. ✅ FIXED `[pending commit]`.** Root causes found by testing directly on the Pi: (1) `tailscale_install()` never unlocked the read-only rootfs before running `pacman`/`systemctl enable`, so both silently failed — fixed by wrapping in `_rw()`/`_ro()`. (2) `tailscale up` on a never-authenticated node prints a login URL then blocks; the old code's 30s timeout discarded all output including that URL — `sh()` now recovers partial output from `subprocess.TimeoutExpired`, and `tailscale_ctl()` extracts the URL and returns it as `login_url`, which both the cockpit's Network page and the Stealth page now render as a clickable "sign in" link instead of a lost toast. (3) `tailscale up`/`down` also need brief rootfs write access for tailscaled's state file — same `_rw()`/`_ro()` wrap. (4) nginx's default 60s `proxy_read_timeout` could cut off a slow install — bumped to 180s for `/mb/net/`. Verified end to end on the live Pi: install → enable → `tailscale up` → real `https://login.tailscale.com/...` URL returned, filesystem correctly relocked read-only after. **Remaining: Raj needs to open the login link himself to complete the OAuth handshake — that step can't be done on his behalf.**
- **B2 — VNC (Remote access) not working.** "Optional VNC client access" does nothing. kvmd-vnc service enable/config + Stealth toggle wiring to verify.
- **B3 — Two-factor login (2FA) not working.** TOTP enable/verify path broken; login page has a "2FA code" field but backend flow is incomplete.
- **B4 — System page has empty/`—` fields.** Health → Uptime shows `—`; Identity & anonymity → MAC address `—`, USB serial `—`. Values exist elsewhere but aren't surfaced here.
- **B5 — Identity spoof not fully applied / real model leaks.** Monitor still reads as "PiKVM V4 Mini" somewhere; video + keyboard/mouse not fully presented as realistic devices at the hardware/descriptor level (not just labels in the UI). USB serial blank.
- **B6 — Login page looks like stock PiKVM.** The `/login/` page visually matches the original PiKVM login → breaks the "no PiKVM tells" rule.
- **B7 — Stealth link visible in main nav.** The main cockpit shows a "Stealth" item in the left sidebar; it should be hidden (anonymity), reachable only by those who know the direct URL.

---

## 3. Phased roadmap (pending work)

### Phase 1 — UI/UX redesign (professional, glassy)
Goal: one cohesive, professional glass UI across all pages; drop the neon "cyberpunk" look; login page that in no way resembles PiKVM. Dependency-free (no CDN).
1. Design a shared glass theme (tokens: blur, translucency, subtle borders, restrained accent) and apply to the main cockpit.
2. Restyle the **Stealth** page from cyan/violet HUD → same professional glass theme (keep it functional, just not "funny colored").
3. Redesign the **login page** — distinct layout/branding from PiKVM (B6).
4. Hide the **Stealth** nav link from the main UI (B7); keep the page reachable by direct URL only. Do not reference stealth anywhere in the main UI.

### Phase 2 — Page & navigation cleanup (Power & Media)
Goal: remove what Raj doesn't use; keep the nav honest.
1. **Remove Virtual Media (MSD)** entirely — not used, matches scope exclusion (no ISO mounting).
2. **Power (ATX):** not physically wired. **Decision needed (D1)** — remove, or keep but hide/grey until an ATX cable is detected.
3. **Wake-on-LAN:** verify it does anything useful over WiFi (no LAN cable). **Decision needed (D2)** — keep only if it works for the target; otherwise remove.
4. Rework/rename the "Power & Media" page after the above (may collapse into System or disappear).

### Phase 3 — Network / WiFi management
Goal: full WiFi control from the UI (parity with old MagicBridge v1/v2) + working Tailscale.
1. **Saved-network manager:** list saved SSIDs, add new, edit password, forget/remove, set priority. Backed by `wpa_supplicant-wlan0.conf` (reuse the safe write path proven in the portal fix).
2. **Fix Tailscale (B1):** install, up/down, Funnel on/off, Lockdown on/off, show login/auth URL and status.

### Phase 4 — Identity spoofing completeness (video + USB)
Goal: the bridge presents only realistic hardware; zero PiKVM/RPi/V4-Mini tells anywhere.
1. **Monitor/EDID:** apply a realistic monitor EDID for real (verify target reads it), remove the "PiKVM V4 Mini" leak (B5). Surface full, detailed monitor info.
2. **USB keyboard/mouse:** ensure the OTG gadget actually presents the chosen realistic vendor/product/serial (not just UI labels); populate USB serial.
3. **Cross-check:** every identity field on the main System page reflects the real applied spoof (fill MAC + USB serial, B4).

### Phase 5 — System page enrichment (main UI, view-only)
Goal: richer, live, read-only telemetry on the main System page.
1. **WiFi latency** (RTT to gateway / signal strength).
2. **Video/stream latency** (capture→encode→client, plus fps/bitrate).
3. **More detailed device details** (realistic, branded — no PiKVM tells).
4. **More detailed monitor details** (from the applied EDID).
5. **Connected clients panel:** how many are on `magicbridge.local`, their IPs and device/User-Agent details.
6. **Tailscale peers:** connected peers with hostname, OS, and approximate location/device details.

### Phase 6 — Remote access & 2FA
1. **Fix VNC (B2):** kvmd-vnc enable/config, wire the Stealth toggle, confirm a VNC client can connect.
2. **Fix 2FA (B3):** TOTP enroll + verify, enforce at login, recovery path documented.

---

## 4. Decisions (locked 2026-07-17, defaults chosen so work isn't blocked — reversible)

- **D1 — Power (ATX), revised during Phase 2:** true auto-detection turned out to be impossible — kvmd has no way to sense whether the ATX header pins are physically wired to a target motherboard (it only reads GPIO pin state, which floats/reads-off either way). Kept the card visible with an explicit note that it needs the header wired to do anything, instead of faking a "detected" state.
- **D2 — Wake-on-LAN:** removed. Can't wake anything meaningful over a WiFi-only link with no wired NIC on the target.
- **D3 — Stealth access:** no nav link in main UI; reachable only via direct `/stealth/` URL, gated by the existing stealth password.
- **D4 — "Power & Media" page fate:** MSD removed, WoL removed, ATX hidden pending cable detection → page folds into System (or the nav item drops entirely if nothing survives after Phase 2 work lands).

---

## 5. Changelog (recent fixes)

- **2026-07-17 · `[pending commit]`** — Phase 3 shipped: **Tailscale (B1) fixed** (see bug entry above — rootfs unlock, login-URL recovery, nginx timeout). **Saved-WiFi manager added** to the Network page: lists saved SSIDs with which one is currently connected, "Forget" to remove one. **Bonus fix found while in this code:** `wifi_connect()` had the *exact same* `wpa_passphrase`-on-SSIDs-with-spaces bug that caused the whole captcaptive-portal outage earlier today (see `magicbridge_captive_portal_wifi_apply` memory) — it silently failed to save credentials entered from the main Network page's "Connect" button too. Replaced with the same plain-quoted-psk + dedupe-by-SSID approach proven in the portal fix. Verified the write/replace/dedupe logic directly on the Pi without disrupting the live WiFi link (real saved networks — Staff, Quality Inn- Office — confirmed untouched throughout).
- **2026-07-17 · `7ae5597`** — Phase 1 UI redesign shipped: shared graphite/glass theme (backdrop-filter blur + translucency) applied to the main cockpit and the Stealth page; Stealth page's neon cyan/violet palette + monospace HUD font replaced with the cockpit's palette/font; Stealth nav link removed from the main sidebar and all "Stealth"/"anonymity" wording stripped from the System page's Identity card (renamed "Device identity", link removed); login page rebuilt from scratch (own CSS, no longer reuses kvmd's `login.css` layout) — kept kvmd's `main.js`/window-manager stylesheets so error dialogs still render, only the login-box layout is custom. Deployed via SFTP; server responded 200/302/401 as expected on `/login/`, `/mb/ui/`, `/stealth/`. **Not yet visually confirmed in a browser** — Claude-in-Chrome extension was disconnected during this session, so this was verified structurally (HTML balance, HTTP status codes) but not by eye. **Action for Raj:** hard-refresh (Ctrl+Shift+R) `magicbridge.local/login/`, `/mb/ui/`, and `/stealth/` and flag anything off.
- **2026-07-17 · `e909cbf`** — Captive portal, final fix: renamed `rw()/ro()` helpers to `mb_rw/mb_ro` (a function named `rw` calling `rw` recursed forever and crashed the credential save mid-write); portal.py now ends only on a real submit so captive-portal probes no longer close the hotspot early. Verified: Pi saved creds and connected to WiFi.
- **2026-07-17 · `cbda878`** — Captive portal: save WiFi creds as a plain quoted passphrase (not `wpa_passphrase`, which failed on SSIDs with spaces) and reboot to apply (in-place AP→station switch is flaky on brcmfmac); hotspot returns on next boot if creds are wrong.
- **2026-07-17 · `552f289`** — Captive portal: run the provisioning script via `bash` in the unit (git-reset drops the +x bit → 203/EXEC), move logs + dnsmasq leases to `/run` (read-only rootfs), dnsmasq `bind-dynamic` to coexist with systemd-resolved, keep the hotspot up in a loop.
- **Earlier (see git log):** relative-mouse fix, WebRTC (Janus version + keyframe recovery), MJPEG single-encoder default, click-to-capture UX, kvmd-otg gadget recovery, anonymity/identity model, branding strip.

---

## 6. Working manual recovery notes (keep handy)

- **Reach the Pi with no network:** serial console COM8 @115200 (CP210x), login root/root.
- **Manually connect WiFi over serial** (when AP is idle, wlan0 not in AP mode):
  `pkill hostapd/dnsmasq; ip link set wlan0 down; iw dev wlan0 set type managed; ip link set wlan0 up; systemctl restart wpa_supplicant@wlan0; systemctl restart systemd-networkd` → associates + DHCP in ~15s.
- Backgrounded `reboot &` over serial gets SIGHUP'd on session close — issue reboot synchronously or via `systemd-run --on-active=`.
- Filesystem is read-only; unlock with `command rw` / relock `command ro` (never shadow those names in a shell function).
