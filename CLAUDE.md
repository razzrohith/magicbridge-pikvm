# CLAUDE.md — MagicBridge PiKVM (session entry point)

You are working on **MagicBridge PiKVM**: the MagicBridge experience ported onto
the **PiKVM V4 Mini / kvmd** platform (a fork + rebrand + our stealth/agent/UI
layer). Read `docs/MAGICBRIDGE_SYSTEM.md` first — it is the authoritative shared
brain (purpose, anonymity model, two-project architecture, history, roadmap, and
how this repo relates to `magicbridge-diy`).

This repo already has a rich doc set — use it:
- `START_HERE.md` — orientation
- `brain/01..07` — overview, hardware/access, architecture, features, **debug
  journal**, deploy runbook, gotchas cheatsheet
- `PROJECT_TRACKER.md`, `TASK_TRACKER.md` — status + backlog
- `docs/FEATURES.md`, `docs/PORTING.md` — feature map + kvmd port notes
- `docs/MAGICBRIDGE_SYSTEM.md` — the shared system brain (see it first)

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

## Right now
Rebrand `MagicBridgeV2`→`MagicBridge` committed; **deploy to Pi 209 pending the
device being online** (run `align_pi.py`). Port the DIY EDID-portability *idea*
where relevant. Janus/WebRTC verify is the standing latency task.
