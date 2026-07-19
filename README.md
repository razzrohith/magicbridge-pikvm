# MagicBridge PiKVM

> **Project name: "MagicBridge PiKVM".** Sibling project = **"MagicBridge DIY"** (hand-built Pi 4 + C790 + bamboo case, repo `MagicBridge`). This repo is still named `MagicBridgeV2` on GitHub for now — same project. Old V1/V2/V3 labels retired.

**A professional, self-hosted KVM-over-IP platform for the PiKVM V4 Mini — built on the proven PiKVM/kvmd core, wrapped in the MagicBridge experience.**

MagicBridge PiKVM stands on the battle-tested **kvmd** engine that ships with the official PiKVM V4 Mini (instead of hand-building the capture/HID/power pipeline from scratch the way **MagicBridge DIY** does), and layers the features that make MagicBridge *MagicBridge* on top:

- **Stealth USB identity** — spoof VID/PID/serial/manufacturer, live profile switching, safe-mode.
- **AI Agent + Macros** — natural-language → keystrokes, macro runner (keys stored server-side).
- **Network toolkit** — WiFi manager, Tailscale + Funnel, DuckDNS, MAC spoofing, Tailscale-only lockdown.
- **Wake-on-LAN, mouse jiggler, typing jitter** and the rest of the MagicBridge quality-of-life layer.
- **A rebranded, professional web UI** — the MagicBridge look, wired to the kvmd + MagicBridge APIs.

Everything you get from PiKVM natively — smooth **H.264 / WebRTC** video, **virtual USB drive (MSD)** boot, real **ATX** power control, **OLED**, **EDID** spoofing, **VNC**, full keymaps — just works. MagicBridgeV2 adds the magic and the brand.

---

## The one magic command

After flashing the **official PiKVM OS** image to the CM4/SD card and booting the V4 Mini once, run:

```bash
curl -fsSL https://raw.githubusercontent.com/razzrohith/MagicBridgeV2/main/magic-install.sh | sudo bash
```

That single command turns a stock PiKVM box into a fully-branded MagicBridgeV2 unit: it rebrands the OS (hostname, mDNS, OLED splash, web UI, MOTD), installs the MagicBridge add-on services, wires nginx and kvmd overrides, and enables everything. Reboot and you're on `https://magicbridge.local/`.

> **Why PiKVM OS underneath and not plain Raspberry Pi OS?** The V4 Mini's HDMI capture is a Toshiba TC358743 CSI bridge that needs a specific device-tree overlay + EDID firmware, plus the read-only root filesystem, OLED and ATX drivers. PiKVM OS ships all of that working. Rebuilding it on Debian/Raspberry Pi OS means re-fighting the exact CSI-capture problem MagicBridge V1 was stuck on. V2 rebrands the PiKVM base instead — you get their hardware work *and* your identity.

---

## Architecture (hybrid)

```
[Target PC] ──HDMI+USB+ATX──▶ PiKVM V4 Mini (CM4, PiKVM OS, read-only)
                                 │
      ┌──────────────────────────┴───────────────────────────┐
      │  NATIVE (kvmd) — untouched, works day one             │
      │  video H.264/WebRTC · HID · MSD · ATX · OLED · EDID   │
      │  · WOL · VNC · macros · jiggler · full keymaps        │
      └──────────────────────────┬───────────────────────────┘
                                 │  MagicBridgeV2 add-on layer
      ┌──────────────────────────┴───────────────────────────┐
      │  magicbridge-stealth  · USB identity / MAC spoof      │
      │  magicbridge-agent    · AI + macro runner (sidecar)   │
      │  magicbridge-net      · DuckDNS · lockdown · WiFi     │
      │  MagicBridgeV2 web UI · rebrand · OLED splash         │
      └──────────────────────────┬───────────────────────────┘
                                 ▼
             kvmd nginx TLS :443  (single front door)
             Browser (MagicBridgeV2 UI) · VNC · API
```

See `docs/ARCHITECTURE.md` for detail.

## Repo layout

| Path | What |
|---|---|
| `magic-install.sh` | The one-command installer (fresh PiKVM OS → MagicBridgeV2) |
| `uninstall.sh` | Cleanly reverts to stock PiKVM |
| `branding/` | Name, colours, hostname, OLED splash, UI overrides — edit `branding.env` to reskin |
| `services/` | MagicBridge add-on services (Python) that run alongside kvmd |
| `systemd/` | Unit files for the add-on services |
| `nginx/` | Extra location blocks merged into kvmd's nginx |
| `kvmd-overrides/` | `override.d/` YAML + EDID applied to kvmd |
| `web/` | The rebranded professional MagicBridgeV2 UI |
| `tools/` | Dev tooling — GitHub sync/push, etc. |
| `docs/` | Architecture, install, porting notes |

## Status

**Running on hardware.** MagicBridge is installed and live on a PiKVM V4 Mini: the cockpit (a port of the MagicBridge DIY UI onto kvmd) at `/mb/ui/` and the hidden stealth panel at `/stealth/`. Track progress in `TASK_TRACKER.md`.

## License & attribution

MagicBridgeV2 is a derivative of PiKVM (`kvmd`, `ustreamer`), which are licensed **GPLv3**. MagicBridgeV2 is therefore released under **GPLv3** — see `LICENSE`. Original PiKVM copyright and attribution are preserved in `NOTICE`. You are free to run, study, modify and share this; if you distribute it you must keep it open under GPLv3 and preserve attribution. The MagicBridge name, branding and add-on code are © Raj.
