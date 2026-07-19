# CLAUDE.md — MagicBridge PiKVM (session entry point)

You are working on **MagicBridge PiKVM**: the MagicBridge experience ported onto
the **PiKVM V4 Mini / kvmd** platform (a fork + rebrand + our stealth/agent/UI
layer). Read `docs/MAGICBRIDGE_SYSTEM.md` first — it is the authoritative shared
brain (purpose, anonymity model, two-project architecture, history, roadmap, and
how this repo relates to `magicbridge-diy`).

Docs (the set was trimmed to these essentials):
- `docs/MAGICBRIDGE_SYSTEM.md` — the authoritative shared brain (read first)
- `docs/IMAGING.md` — building a flashable `.img` + the first-boot flow
- `TASK_TRACKER.md` — living status + backlog
- `README.md` — orientation

## What this project is
Free/private alternative to TinyPilot, built on kvmd so we inherit its mature
video/HID/WebRTC. Same mission and **anonymity model** as DIY
(`MAGICBRIDGE_SYSTEM.md` §2): stealth on a machine Raj owns — the target must not
detect a KVM/Pi. All "PiKVM/kvmd/Raspberry Pi" tells are stripped; on-screen
brand is plain **MagicBridge**; upstream GPLv3 credit stays in LICENSE/NOTICE.

## The device
- Pi @ **172.16.20.209**, SSH **`root` / `root`** (no sudo needed).
- `/opt/magicbridge` on the Pi **IS a git tree** → deploy via **`align_pi.py`**
  (git fetch + reset to origin/main). Quick UI pushes via `deploy_index.py` (SFTP).
- Dev→GitHub sync: `sync_and_push.py` (Cowork build → `E:\Startup\magicbridge-pikvm`
  git → GitHub). Then `align_pi.py` to the Pi.
- Capture: kvmd-native; CM4 supports up to 1080p60 (4 lanes) — unlike DIY's 2-lane cap.

## Repo layout (highlights)
- `services/` — our add-on services (magicbridge-net, -stealth, -agent)
- `web/` — the cockpit UI (`index.html`, login, stealth panel)
- `kvmd-overrides/`, `systemd/`, `nginx/`, `provision/` — platform integration
- `branding/` — `branding.env` (single file to reskin the whole product)
- `deploy_*.py`, `align_pi.py`, `sync_and_push.py` — deploy tooling

## How to work
- Reach the Pi over SSH from the native shell.
- Change → `sync_and_push.py` (commit+push) → `align_pi.py` (deploy) → verify.
- Service names `magicbridge-net` / `-stealth` / `-agent` are **systemd units**,
  NOT brand strings — never rename them.
- To reuse a DIY solution, read the sibling repo at `E:\Startup\magicbridge-diy`
  and adapt to the kvmd stack (see `MAGICBRIDGE_SYSTEM.md` §8). Never blind-copy.

## Safety (always)
SAFE (in-project, reversible, no system impact) → do it. RISKY (OS/system files,
files outside the project, security/network settings, irreversible loss, or a
hard-to-undo change to the live Pi) → **stop, state what/why/impact, wait for an
explicit yes.** Never weaken the anonymity model. State exactly what a deploy
pushes; routine redeploys are SAFE, boot/network/kvmd-core changes are RISKY.

## Two mechanisms only
The product presents exactly two web faces (login gates both):
- **Regular site** — the cockpit at `/mb/ui/` (a port of the MagicBridge DIY UI
  onto kvmd: DIY's JSON `/ws` bridged to kvmd's binary `/api/ws`, MJPEG via kvmd
  streamer, WebRTC via kvmd's own `janus.js`, and a fetch shim mapping DIY's
  `/api/*` to kvmd + our `/mb/*` sidecars).
- **Stealth mode** — the hidden panel at `/stealth/` (identity/MAC/EDID editing).

Native kvmd pages (`/kvm/`, terminal, `/vnc/`) are redirected to `/mb/ui/` so
nothing else is reachable.

## Right now
DIY UI is live at `/mb/ui/`. Remaining polish: the System sub-tabs
(Security/Power/Devices), hide non-applicable DIY features (WoL/OLED), and give
the stealth page the DIY look. HDMI/USB not connected → video/input untested E2E.
