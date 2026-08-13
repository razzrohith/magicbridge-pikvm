# Handoff → MagicBridge PiKVM (from DIY, sessions of 2026-08-04 → 08-12)

Paste this whole file into a `magicbridge-pikvm` session.

**Read `docs/MAGICBRIDGE_SYSTEM.md` first.** This supersedes
`SIBLING_HANDOFF_2026-08-04.md` (that one is folded in below).

## How to use this

The DIY unit is a hand-rolled stack (own aiohttp backend, own `index.html`, own
HID/video code). The sibling runs **kvmd**, so kvmd owns HID, capture and its own
WebRTC plumbing. **Do not port DIY code.** But I checked your tree before writing
this, and you DO have your own `web/index.html`, `web/janus.js`, `web/stealth/`,
`web/login_index.html`, Tailscale, and iptables handling. So a lot of this lands
squarely in code you own.

I grepped your repo for `ice_ignore` and `rtp_port` and found **neither**, which
is why section A is first: those are almost certainly live bugs on your unit too.

---

## A. DO THESE FIRST — you have the same components, unpatched

### A1. Janus offers a DEAD Tailscale ICE candidate → WebRTC never delivers
**This was the single biggest bug of the session and cost hours to find.**

Symptom on DIY, and it will look identical on yours: WebRTC "always fails and
falls back to MJPEG". The Janus log showed the DTLS handshake **completing** and
then:

```
[ERR] [ice.c:janus_ice_outgoing_traffic_handle] ... only sent -1 bytes? (was 1166)
```
repeated **51,154 times**. Every media packet failed, the browser got no frame,
hit its connect timeout, and dropped to MJPEG. Forever.

Cause: Janus gathers an ICE candidate from **every up interface**, including
`tailscale0`. That interface stays UP even when the tailnet is OFFLINE, so the
candidate is unreachable and every send to it errors.

**Fix, and note the nuance — do NOT just blacklist it permanently.** Blacklisting
kills low-latency remote WebRTC, which is exactly what you want when you're away
from the LAN. Decide per stream start:

```python
# tailnet UP   -> ice_ignore_list = "vmnet"              (allow tailscale0, remote WebRTC works)
# tailnet DOWN -> ice_ignore_list = "vmnet,tailscale0"   (skip the dead path)
# read BackendState from: tailscale status --json
```
DIY does this in `video.py::_tune_janus_ice()` (commit `1cf4fe3`), called on each
stream start, restarting Janus only when the value actually flips. Copy the
*idea* into whatever starts your capture.

### A2. Firewall has no rule for WebRTC media
DIY's `INPUT` policy is `DROP` with allowances only for TCP 22/80/443 and UDP
5353/67. Inbound RTP survived only while a conntrack entry happened to exist.
Fix: pin Janus's ports and allow exactly those.

```
# janus.jcfg  ->  media: { rtp_port_range = "20000-20100" }
iptables -I INPUT -p udp --dport 20000:20100 -j ACCEPT
```
You have iptables logic in `provision/mb-portal.sh`, `provision/mb-boot-report.sh`
and `services/magicbridge-net/app.py` — check whether media ports are open there.

### A3. MJPEG readers leak, and they strangle WebRTC
Measured on DIY: **7 concurrent MJPEG clients** from two browser tabs. At 1080p
that is >100 Mbit/s of duplicate video on the same Wi-Fi as the WebRTC stream,
which starves it into its connect timeout, which triggers another fallback, which
opens another reader. A death spiral, and it also showed up as 164ms control
latency.

Cause: the retry path only assigned a new `.src`. That does **not** reliably tear
down an in-flight `multipart/x-mixed-replace` stream. Fix (one line):

```js
img.removeAttribute('src');        // force the old request closed FIRST
img.src = '/stream?_=' + Date.now();
```
Check every retry path in your `web/index.html`: anti-stall reconnect, WebRTC
fallback, WebSocket reconnect. Verify with ustreamer's `/state` → `stream.clients`;
it should return to 1, not climb.

### A4. Client timers that kill healthy connections
Two DIY defaults were actively causing the drop-outs they were meant to prevent.
Check your `janus.js`/client for equivalents:

| Timer | Was | Now | Why |
|---|---|---|---|
| WebRTC connect timeout | 8s | **20s** | A laptop offers many candidates (LAN + VPN + Tailscale + several 169.254). ICE legitimately needs longer to walk to the good pair; 8s tore down connections mid-negotiation |
| "frames stalled" watchdog | 6s | **30s** | An **idle desktop is static and sends no frames by design**. No statistic distinguishes "nothing changed on screen" from "stream died", so this demoted healthy sessions |
| `ustreamer --drop-same-frames` | 30 | **10** | Keeps a still screen ticking a few fps so the receiver stays fed |

**The lesson worth carrying over:** aggressive auto-recovery is worse than none.
Both of these were *my own* recovery features causing the failure they existed to
fix. If you add stall detection, be very conservative.

---

## B. STEALTH — audit your equivalents

| # | Finding on DIY | What to check on yours |
|---|---|---|
| B1 | `mb-hdmi-init.sh` logged to `/var/log/mb-hdmi-init.log` on the **SD card**: 178 lines, timestamped, every boot + the exact resolution of every machine ever attached. The image builder never stripped it, so the distributed `.img` shipped the builder's own capture history | Grep every log path for anything outside the RAM disk. Add an assertion in `provision/build-image.sh`'s sanitize block so it cannot silently return |
| B2 | `/api/status` hardcoded `{"name":"DELL P2419H","spoofed":true}` for every CSI unit, even when EDID application had fallen back to a generic test EDID that drops the 1080p cap. **The UI asserted a disguise that was not on** | Report the identity actually read back from the chip (`v4l2-ctl --get-edid`, parse bytes 8-9 for the manufacturer, descriptor tag 0xFC for the name). Cache it, it is on the status poll path |
| B3 | Wake-on-LAN broadcast accepted any string → a hostname would make a stealth device do a **real DNS lookup** and unicast the target's MAC off-LAN | Validate as IPv4 only |
| B4 | The stealth panel attached its auth-log FileHandler unconditionally, with a comment accepting a fallback "to a plain directory on disk" if the tmpfs was missing → logins/MACs/SSIDs on the card | Gate on `os.path.ismount()`. Log to RAM or not at all. **Do NOT** "fix" it with `RequiresMountsFor=` — a mount failure would then stall a headless boot with no SSH |

---

## C. SINGLE-FAULT CHAINS — check for the same shape

| # | DIY bug | The shape to look for |
|---|---|---|
| C1 | A mistyped USB **VID/PID** bricked ALL HID on next boot. The field was free text; configfs parses with `kstrtou16(base 0)`, so `046d` (what `lsusb` prints, the natural typo) is invalid; `mb-gadget.sh` does `echo "$VID" > idVendor` under `set -e` and **aborted before creating the keyboard, the mouse, or binding the UDC**. Web UI still came up, so it read as "input broke for no reason". SSH-only recovery | Any operator-editable value that a boot script writes to configfs/sysfs under `set -e` |
| C2 | One corrupt `config.json` reset the device to the **public default password with 2FA off**. The auth bootstrap correctly failed closed, but a sibling function read the same file, swallowed the parse error into `{}`, and wrote that back — wiping auth. Next boot found no hash and bootstrapped the default | Every config reader: does a **parse error** get treated as "empty"? If so it will eventually clobber. Fail closed and refuse to write over a file you could not read |
| C3 | Four config writers used `open(path,'w')` + `json.dump` (truncate first, no fsync, no atomic rename) on the file holding the password hash | Use a temp-file + fsync + `os.replace` writer everywhere, not just in the newest code |

---

## D. TARGET COMPATIBILITY — hardware truths, not code bugs

| Finding | Detail |
|---|---|
| **iPadOS ignores absolute-mouse CLICKS** | Verified hands-on. Pointer moves, hover highlights render, but **no press variant works** (70/300/800ms, double-click, move-then-click). Switching to relative (boot-protocol mouse) made the identical click work instantly. Do NOT "fix" by making the absolute interface claim boot protocol: a boot-subclass device must send the 3-byte boot report if the host selects boot protocol, which would break the BIOS/UEFI case that matters most for a KVM. Relative is also the stealthier identity |
| **Absolute mouse needs the target's real screen rect** | An iPad mirrors its 4:3-ish screen into a 16:9 signal, so iPadOS pillarboxes it: measured 173px bars left/right, 33px top/bottom of a 1280x720 frame. Absolute coords address the **target's** screen, so mapping across the whole captured frame was off by up to ±173px (zero error dead-centre, worst at the edges). DIY added a "screen area" calibration, source-tagged so it auto-reverts on a different target |
| **C790 I2S audio is a driver dead-end** | `arecord` EIOs at every sample rate. The supported path is a USB-audio adapter. Also: DIY was writing the Janus audio block to a folder Janus never reads (`/opt/janus/lib/janus/configs/` vs the actual `--configs-folder`) — worth checking yours |
| **Extended-desktop confusion** | Not a bug, but it cost real debugging time: with the target in **extended** mode the KVM shows the second display while the cursor, Start menu and keyboard focus live on the primary. Control looks dead. Tell the operator to make the captured display primary, or use duplicate mode. A Caps Lock LED round-trip (`01`→`03`→`01` read back from `/dev/hidg0`) is a great way to prove the keyboard really is reaching the host |

---

## E. UI/UX — you have your own `web/` and stealth panel

| Item | What changed on DIY and why |
|---|---|
| E1 | **Tooltips: 1-3 words.** I first wrote full sentences and Raj rejected them twice. A tooltip should name the thing, not explain it: "Connected viewers", "Control delay", "Release control" |
| E2 | **Helper notes: one short line.** 12 of 23 notes were over 90 chars; one Mouse Mode card had ~620 characters of help above the two buttons it described, pushing the controls off screen. All rewritten to a single line |
| E3 | **Collapse long lists.** Saved Wi-Fi networks rendered every entry expanded plus an always-open add form. Now native `<details>` (no JS to fail, keyboard/screen-reader accessible), collapsed by default, with the count in the summary. One exception: auto-open when the list is empty so a fresh unit does not hide its only actionable state |
| E4 | **Stealth panel restyled to professional.** The neon-cyan/purple cyberpunk theme (glow shadows, scanline grid, card corner brackets, a "breathing" animation, uppercase monospace everywhere) was replaced with a neutral slate palette and one restrained blue accent, system-sans headings, monospace kept only for values. Done by editing **CSS values only** so no class/id/DOM/Jinja token changed. If your `web/stealth/` and `theme.generated.css` share that look, the same treatment applies |
| E5 | **Update panel showed only the newest commit.** Now lists every pending commit's subject with the `type(scope):` prefix stripped, in a full-width block so long text cannot collide with a label |
| E6 | **Two cursors.** Under pointer lock the browser hides the real cursor, so a "predictive dot" plus the target's own pointer meant two arrows that never agreed. Worse, when I later auto-hid ours in absolute mode the operator ended up with **no cursor at all** on targets whose pointer is not visible in the capture. Rule: never leave the operator with zero cursors; make hiding opt-in |

---

## F. WORTH LIFTING — auth and session hardening

| Item | Detail |
|---|---|
| F1 | **Logout did not revoke anything.** Stateless HMAC tokens meant a captured 30-day "remember me" cookie kept authenticating everything after logout. Fixed with a signed `session_epoch` in the token body that logout increments. Accept the trade-off: it logs out all devices at once |
| F2 | **No RTC on a Pi.** A token minted before a reboot was rejected while fake-hwclock sat on a pre-NTP time. On an air-gapped LAN that rejection is permanent. Allow a backwards clock step (`-3600 <= age <= ttl`); `ts` is inside the signed body so it cannot be forged |
| F3 | **Login oracle.** Wrong password said "Incorrect password" while right-password-wrong-2FA said "Incorrect or expired 2FA code", telling a brute-forcer when they had the password. One message when 2FA is on |
| F4 | **2FA re-enrollment** needed only a session, not the password, so a borrowed session could silently swap the second factor and lock the owner out. Require the password when 2FA is already enabled |
| F5 | **Bcrypt missing = silent lockout.** If the module vanished but the stored hash is bcrypt, every login failed as "incorrect password". Detect and say so |

---

## G. Provisioning / other

| Item | Detail |
|---|---|
| G1 | **One character stranded units.** The initial Wi-Fi check had been fixed to `grep -qE '^connected'` so NetworkManager's `connected (site only)` counts as up, but the **post-submit verify still used `^connected$`**. On an air-gapped LAN the correct password associated, the loop timed out, and the code **deleted the good profile** and reopened the setup hotspot. Permanently unreachable with valid credentials. Check both call sites |
| G2 | Provisioning wrote the target Wi-Fi PSK `0644` in a `0755` directory. Create it `0600` |
| G3 | The uninstaller left five units enabled pointing at deleted files |
| G4 | nginx discards **all** inherited `add_header` in any location that defines its own, so the main UI page and `/static/` got none of the five security headers. Repeat them per-location. Do not add HSTS with a self-signed cert |
| G5 | An OLED that flapped (`I2C device not found on 0x3C`) was fixed with `dtparam=i2c_arm_baudrate=50000`. Device detected + clean power = marginal wiring; slowing the bus fixed it |

---

## H. Method worth copying

The audit that produced most of section B/C/F: **9 parallel review lenses** over
the codebase (anonymity, auth, injection, backend concurrency, video, HID, web
client, dashboard, provisioning), then **3 adversarial verifiers** that re-checked
every reported finding against the code. Of **51 raised, 40 survived and 11 were
false**. Reviewers over-report; the verification pass is what makes the output
trustworthy. It also caught two regressions in my own fixes before they shipped.

---

**Suggested ask for that session:** work section A first and measure it (Janus
send-failure count, `stream.clients`), then audit B and C against the kvmd fork
and your own `services/`, then treat D as compatibility notes, E/F/G as parity
work. Report which items were already handled and which needed a real fix.
