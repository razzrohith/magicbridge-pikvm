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
| USB identity presets + MAC spoof + monitor(EDID) spoof (Stealth page) | ⚠️ Present but not fully verified/applied (Phase 4) |
| Power (ATX) / Virtual Media / Wake-on-LAN pages | ⚠️ Present, questioned for removal (Phase 2) |
| Tailscale install / bring-up / Funnel | ❌ Not working (B1) |
| VNC remote access | ❌ Not working (B2) |
| Two-factor (TOTP) login | ❌ Not working (B3) |
| Saved-WiFi management (list/edit/forget) in UI | ❌ Missing (Phase 3) |
| UI theme (professional/glassy) & login page distinct from PiKVM | ❌ Redesign needed (Phase 1) |

---

## 2. Open bugs

- **B1 — Tailscale won't install or come up.** Network page: `Install`, `Bring up`, `Funnel on`, `Lockdown` have no effect; Tailscale stays `down`. Needs backend debug (install path, `tailscale up`, auth key handling, funnel/lockdown endpoints).
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

## 4. Decisions needed from Raj

- **D1 — Power (ATX):** remove the panel, or keep it hidden/disabled until an ATX cable is present?
- **D2 — Wake-on-LAN:** keep (if it can wake the target over the current network) or remove?
- **D3 — Stealth access after hiding the link:** rely on the direct `/stealth/` URL + existing stealth password gate, or add a hidden trigger (e.g. key combo) to reveal it?
- **D4 — "Power & Media" page fate:** once MSD (and maybe ATX/WoL) are gone, delete the page or fold the survivors into System?

---

## 5. Changelog (recent fixes)

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
