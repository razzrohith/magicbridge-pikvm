#!/usr/bin/env python3
"""
magicbridge-net - MagicBridgeV2 network toolkit sidecar.

Runs alongside kvmd on 127.0.0.1:8410 (behind kvmd nginx at /mb/net/).
Ports V1's network features onto the PiKVM base WITHOUT touching kvmd:
  - DuckDNS dynamic-DNS updater
  - Tailscale status wrapper
  - Tailscale-only network lockdown (iptables; SSH never touched)
  - MAC address spoofing (persisted; re-applied at boot)
  - WiFi scan/connect (nmcli) - TODO on hardware
"""
from __future__ import annotations
import asyncio
import functools
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/opt/magicbridge/services/common")
try:
    from mbcommon import get_logger, load_config, save_config
except Exception:  # dev-machine fallback
    import logging

    def get_logger(n):
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(n)

    def load_config(n, d=None):
        return dict(d or {})

    def save_config(n, d):
        pass

from aiohttp import web

log = get_logger("mb-net")
PORT = int(os.environ.get("MB_NET_PORT", "8410"))
MAC_RE = r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$"
NETWORKD_DIR = "/etc/systemd/network"


def sh(*args, timeout=15):
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired as e:
        # Some commands (notably `tailscale up` when not yet authenticated) print a
        # login URL and then hang waiting for the browser flow to complete. Recover
        # whatever was captured before the kill instead of losing it — the caller may
        # still need that URL. .stdout/.stderr are bytes or str depending on 'text='.
        def _dec(x):
            if x is None:
                return ""
            return x.decode(errors="replace") if isinstance(x, bytes) else x
        return 124, (_dec(e.stdout) + _dec(e.stderr)).strip()
    except Exception as e:
        return 1, str(e)


# ---- item 37: keep long commands OFF the event loop ------------------
# aiohttp is single-threaded, so a blocking subprocess.run inside an `async def`
# handler freezes EVERYTHING for its whole duration — every connected client's
# keyboard/mouse and all status polling. A `tailscale install` (pacman) or a
# `wpa_cli scan` is seconds to minutes of a dead KVM. `sh_a` runs the same
# command in the default thread-pool executor so the loop keeps serving input.
# Rule: anything that can exceed a few hundred ms (network, package installs,
# scans, iptables batches, systemctl start/stop, kvmd-edidconf --apply) goes
# through sh_a / run_blocking; cheap local reads (git rev-parse, systemctl
# is-active, reading /proc) stay inline — an executor hop isn't free either.
async def sh_a(*args, timeout=15):
    """Async `sh`: identical contract, executed off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(sh, *args, timeout=timeout))


async def run_blocking(fn, *a, **kw):
    """Run one blocking helper (usually a BATCH of sh() calls) off the event loop.
    Batching a whole sequence into a single executor hop is better than awaiting
    each command separately — fewer context switches and the batch stays coherent."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *a, **kw))


async def health(_):
    return web.json_response({"ok": True, "service": "magicbridge-net"})


async def sysinfo(_):
    """GET /mb/net/sys — uptime/load/hostname (kvmd's /api/info doesn't expose uptime)."""
    up = None
    try:
        up = float(open("/proc/uptime").read().split()[0])
    except Exception:
        pass
    load = None
    try:
        load = os.getloadavg()
    except Exception:
        pass
    return web.json_response({"ok": True, "uptime": up, "load": load,
                              "hostname": os.uname().nodename})


def _iface_mac(iface):
    """Actual current hardware address of an interface (what the network sees now)."""
    try:
        return open("/sys/class/net/%s/address" % iface).read().strip()
    except Exception:
        return None


def _wired_iface() -> str:
    """Find the wired NIC by HARDWARE, never by guessing its name.

    The old ("wlan0", "eth0") tuple silently missed real ports: Pi kernels with
    predictable names call it end0, and a USB NIC gets something else entirely. On
    those units /status reported no wired MAC at all and a manual spoof targeted an
    interface that does not exist — so the wired Raspberry Pi OUI kept leaking with
    the UI showing nothing wrong.

    A physical wired port is the one that has a /device symlink (rules out lo, tun,
    bridges and veth, which have none) and no wireless attributes.
    """
    base = "/sys/class/net"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return ""
    for name in names:
        if name == "lo":
            continue
        path = os.path.join(base, name)
        # wireless: either a legacy /wireless dir or the modern phy80211 link
        if os.path.isdir(os.path.join(path, "wireless")) or os.path.exists(os.path.join(path, "phy80211")):
            continue
        if not os.path.exists(os.path.join(path, "device")):
            continue
        return name
    return ""


async def _lockdown_live() -> bool:
    """Is lockdown ACTUALLY in force right now? The MB_LOCKDOWN chain can survive while
    the `-j MB_LOCKDOWN` jump in INPUT does not, and nothing on this system persists
    iptables across a reboot — so the jump is the only honest signal (item 42).

    BOTH families must be in force: nginx listens on IPv6 too, so a v4-only jump
    leaves the surface open over v6. Report locked ONLY when both are present —
    otherwise a half-applied firewall would show as a green "locked down"."""
    rc4, _o4 = await sh_a("iptables", "-C", "INPUT", "-j", "MB_LOCKDOWN", timeout=6)
    rc6, _o6 = await sh_a("ip6tables", "-C", "INPUT", "-j", "MB_LOCKDOWN", timeout=6)
    return rc4 == 0 and rc6 == 0


async def status(_):
    ts_rc, ts_out = await sh_a("tailscale", "status", "--json", timeout=8)
    cfg = load_config("net", {})
    # Item 42: report the LIVE firewall state, not what we once saved. /status never
    # returned `lockdown` at all, so the UI toggle (which reads s.lockdown) always
    # showed OFF — and after a reboot the rules are genuinely gone while the saved
    # config still says on, i.e. the user believes they're protected and they are not.
    ld_live = await _lockdown_live()
    ld_cfg = bool(cfg.get("lockdown"))
    # Report the LIVE MAC of the active interface (spoofed or not) so the System
    # page never shows a blank — the old code only surfaced a MAC if one had been
    # explicitly spoofed this session.
    wired = _wired_iface()
    macs = {i: _iface_mac(i) for i in ("wlan0", wired) if i and _iface_mac(i)}
    active_mac = macs.get("wlan0") or (macs.get(wired) if wired else None)
    return web.json_response({
        "tailscale": {"up": ts_rc == 0, "raw": ts_out[:2000]},
        "duckdns": cfg.get("duckdns", {"enabled": False}),
        "hostname": os.uname().nodename,
        "mac": {"mac": active_mac, "spoofed": bool(cfg.get("mac"))},
        "macs": macs,
        "lockdown": ld_live,                       # LIVE truth — what the UI toggle shows
        "lockdown_configured": ld_cfg,             # what the user last asked for
        "lockdown_drifted": (ld_cfg and not ld_live),   # e.g. after a reboot: silently OFF
    })


async def net_latency(_):
    """GET /mb/net/latency — WiFi link quality + round-trip time to the gateway.
    Everything is best-effort; missing pieces come back as null rather than erroring."""
    out = {"ok": True}
    # default gateway
    rc, route = await sh_a("bash", "-c", "ip route | awk '/^default/{print $3; exit}'", timeout=6)
    gw = route.strip() or None
    out["gateway"] = gw
    # RTT to gateway (fast, 3 pings)
    if gw:
        rc, ping = await sh_a("bash", "-c", "ping -c3 -W1 -i0.3 %s 2>/dev/null | tail -1" % gw, timeout=8)
        m = re.search(r"=\s*[\d.]+/([\d.]+)/", ping)
        out["rtt_ms"] = round(float(m.group(1)), 1) if m else None
    # signal strength + negotiated bitrate from the WiFi driver
    rc, link = await sh_a("iw", "dev", "wlan0", "link", timeout=6)
    sig = re.search(r"signal:\s*(-?\d+)\s*dBm", link)
    br = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", link)
    ssid = re.search(r"SSID:\s*(.+)", link)
    out["signal_dbm"] = int(sig.group(1)) if sig else None
    out["tx_bitrate_mbps"] = float(br.group(1)) if br else None
    out["ssid"] = ssid.group(1).strip() if ssid else None
    # a friendly 0-100 quality from dBm (−30 great … −90 unusable)
    if out["signal_dbm"] is not None:
        q = max(0, min(100, round(2 * (out["signal_dbm"] + 100))))
        out["quality_pct"] = q
    return web.json_response(out)


def _net_clients_blocking() -> list:
    """`ss` plus a REVERSE-DNS lookup per client. socket.gethostbyaddr is blocking and
    can hang for seconds on each unresolvable address, so with a few peers connected
    this was one of the worst input-freezes in the service — offloaded (item 37)."""
    import socket
    _rc, out = sh("bash", "-c",
                  "ss -Hntu state established '( sport = :443 )' 2>/dev/null | awk '{print $5}'", timeout=8)
    ips = {}
    for peer in out.splitlines():
        peer = peer.strip()
        if not peer:
            continue
        ip = peer.rsplit(":", 1)[0].strip("[]")
        if ip in ("127.0.0.1", "::1", "") or ip.startswith("::ffff:127."):
            continue
        ip = ip.replace("::ffff:", "")
        ips[ip] = ips.get(ip, 0) + 1
    clients = []
    for ip, conns in ips.items():
        host = None
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass
        kind = ("tailscale" if ip.startswith("100.") else
                "lan" if ip.startswith(("192.168.", "10.", "172.")) else "remote")
        clients.append({"ip": ip, "connections": conns, "hostname": host, "via": kind})
    clients.sort(key=lambda c: c["ip"])
    return clients


async def net_clients(_):
    """GET /mb/net/clients — distinct remote peers with an established connection to
    the web UI (:443), i.e. who is currently viewing this bridge. Adds reverse-DNS
    hostname and a LAN/Tailscale/remote classification per client."""
    clients = await run_blocking(_net_clients_blocking)
    return web.json_response({"ok": True, "count": len(clients), "clients": clients})


async def tailscale_peers(_):
    """GET /mb/net/tailscale/peers — connected tailnet peers (hostname, OS, IP,
    online state, and location if the peer advertises one, e.g. exit nodes)."""
    import json as _json
    rc, out = await sh_a("tailscale", "status", "--json", timeout=10)
    if rc != 0:
        return web.json_response({"ok": False, "error": "tailscale not up", "peers": []})
    try:
        data = _json.loads(out)
    except Exception:
        return web.json_response({"ok": False, "error": "unparseable status", "peers": []})
    peers = []
    for _k, p in (data.get("Peer") or {}).items():
        loc = p.get("Location") or {}
        peers.append({
            "hostname": p.get("HostName"),
            "dns": (p.get("DNSName") or "").rstrip("."),
            "os": p.get("OS"),
            "ip": (p.get("TailscaleIPs") or [None])[0],
            "online": p.get("Online", False),
            "exit_node": p.get("ExitNode", False),
            "location": ", ".join([x for x in (loc.get("City"), loc.get("Country")) if x]) or None,
        })
    peers.sort(key=lambda x: (not x["online"], x.get("hostname") or ""))
    self_info = data.get("Self") or {}
    return web.json_response({"ok": True, "count": len(peers), "peers": peers,
                              "self": {"hostname": self_info.get("HostName"),
                                       "ip": (self_info.get("TailscaleIPs") or [None])[0]}})


async def duckdns_update(request):
    body = await request.json()
    domain = body.get("domain", "")
    token = body.get("token", "")
    if not domain or not token:
        return web.json_response({"ok": False, "error": "domain and token required"}, status=400)
    import urllib.request
    url = f"https://www.duckdns.org/update?domains={domain}&token={token}&ip="
    try:
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(url, timeout=15).read().decode())
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    ok = resp.strip() == "OK"
    cfg = load_config("net", {})
    # Only mark DuckDNS "enabled" if the update actually succeeded — a bad
    # domain/token returns "KO", which must not look like a live config (bug D).
    cfg["duckdns"] = {"enabled": ok, "domain": domain, "last": resp, "ts": int(time.time())}
    save_config("net", cfg)
    return web.json_response({"ok": ok, "duckdns_response": resp})


def _lockdown_blocking(on: bool) -> None:
    """Up to a dozen iptables spawns plus a config save (which itself remounts the
    rootfs rw/ro). Offloaded as ONE batch (item 37) — inline, this stalled every
    client's input for the whole sequence, and a half-applied firewall is worse than
    a slow one, so the batch must stay coherent in a single thread."""
    # BOTH families. kvmd's nginx listens on IPv6 as well as IPv4
    # (/etc/kvmd/nginx/nginx.conf.mako: `listen [${https_ipv6}]:${https_port} ssl`),
    # and ip6tables INPUT defaults to ACCEPT — so an IPv4-only lockdown left the
    # ENTIRE web surface reachable over IPv6. "Tailscale-only" was fully bypassable
    # by connecting to the unit's v6 address. Every rule below is mirrored.
    for ipt in ("iptables", "ip6tables"):
        sh(ipt, "-N", "MB_LOCKDOWN")
        sh(ipt, "-F", "MB_LOCKDOWN")
        if on:
            for port in ("80", "443"):
                sh(ipt, "-A", "MB_LOCKDOWN", "-i", "lo", "-p", "tcp", "--dport", port, "-j", "ACCEPT")
                sh(ipt, "-A", "MB_LOCKDOWN", "-i", "tailscale0", "-p", "tcp", "--dport", port, "-j", "ACCEPT")
                sh(ipt, "-A", "MB_LOCKDOWN", "-p", "tcp", "--dport", port, "-j", "DROP")
            rc, _out = sh(ipt, "-C", "INPUT", "-j", "MB_LOCKDOWN")
            if rc != 0:
                sh(ipt, "-I", "INPUT", "1", "-j", "MB_LOCKDOWN")
        else:
            sh(ipt, "-D", "INPUT", "-j", "MB_LOCKDOWN")
    cfg = load_config("net", {})
    cfg["lockdown"] = on
    save_config("net", cfg)


async def lockdown(request):
    body = await request.json()
    on = bool(body.get("on"))
    await run_blocking(_lockdown_blocking, on)
    return web.json_response({"ok": True, "lockdown": on, "note": "SSH (22) never restricted"})


def _mac_link_path(iface):
    return "%s/70-mb-%s.link" % (NETWORKD_DIR, iface)


def _write_mac_link(iface, mac):
    """Persist a spoofed MAC as a systemd-networkd .link file. udev applies it at
    boot BEFORE the interface associates, so the spoof actually survives a reboot
    (the old code only ran `ip link set … address` at runtime and saved a config
    that nothing ever re-read — so the real hardware MAC came back on every boot).
    Needs the rootfs unlocked for the /etc write."""
    _rw()
    try:
        os.makedirs(NETWORKD_DIR, exist_ok=True)
        with open(_mac_link_path(iface), "w") as f:
            f.write("[Match]\nOriginalName=%s\n\n[Link]\nMACAddressPolicy=none\nMACAddress=%s\n"
                    % (iface, mac))
    finally:
        _ro()


def _remove_mac_link(iface):
    _rw()
    try:
        os.remove(_mac_link_path(iface))
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("remove mac link: %s", e)
    finally:
        _ro()


def _mac_clear_blocking(iface: str) -> str:
    """Restore the permanent MAC: ethtool + an interface down/address/up cycle, plus a
    config save. Offloaded (item 37) — an `ip link set down/up` takes real time and the
    sequence must not be interleaved."""
    _remove_mac_link(iface)
    _rc, perm = sh("bash", "-c", "ethtool -P %s 2>/dev/null | awk '{print $NF}'" % iface)
    perm = (perm or "").strip()
    cfg = load_config("net", {}); cfg.pop("mac", None); save_config("net", cfg)
    if re.match(MAC_RE, perm):
        sh("ip", "link", "set", iface, "down")
        sh("ip", "link", "set", iface, "address", perm)
        sh("ip", "link", "set", iface, "up")
    return perm


def _mac_set_blocking(iface: str, mac: str) -> tuple[int, str]:
    """Apply a spoofed MAC (down/address/up), persist the .link file and save config —
    one offloaded batch (item 37); a half-applied MAC change is worse than a slow one."""
    sh("ip", "link", "set", iface, "down")
    rc, out = sh("ip", "link", "set", iface, "address", mac)
    sh("ip", "link", "set", iface, "up")
    _write_mac_link(iface, mac)          # persist across reboot (bug A)
    cfg = load_config("net", {})
    cfg["mac"] = {"iface": iface, "mac": mac}
    save_config("net", cfg)
    return rc, out


async def mac_spoof(request):
    import random
    body = await request.json()
    iface = body.get("iface", "wlan0")
    # Resolve a generic wired request to the ACTUAL port. A caller asking for
    # "eth0"/"eth"/"wired" on a unit whose NIC is end0 (or a USB adapter) would
    # otherwise write a .link for an interface that does not exist: the call
    # reports success, and the real Pi OUI keeps leaking on the cable.
    if iface in ("eth", "eth0", "wired"):
        iface = _wired_iface() or iface
    if body.get("clear"):
        # drop persistence and restore the permanent hardware MAC
        perm = await run_blocking(_mac_clear_blocking, iface)
        return web.json_response({"ok": True, "iface": iface, "cleared": True, "restored_mac": perm or None})
    if body.get("random"):
        mac = "02:%02x:%02x:%02x:%02x:%02x" % tuple(random.randint(0, 255) for _ in range(5))
    else:
        mac = (body.get("mac") or "").strip().lower()
    if not re.match(MAC_RE, mac):
        return web.json_response({"ok": False, "error": "valid mac (aa:bb:cc:dd:ee:ff) or random required"}, status=400)
    rc, out = await run_blocking(_mac_set_blocking, iface, mac)
    return web.json_response({
        "ok": rc == 0, "iface": iface, "mac": mac, "detail": out[:300],
        "persisted": "systemd-networkd .link file — re-applied at boot",
    })


def _tailscale_updown_blocking(action: str) -> tuple[int, str, str | None]:
    """rw -> tailscale up/down (12-15s) -> ro, as ONE offloaded batch (item 37) so the
    rw/ro window stays coherent in a single thread instead of freezing the loop.

    tailscaled needs to persist its state to /var/lib/tailscale on login/logout (key
    material, node state) — the rootfs is read-only outside these brief windows, so
    unlock for the duration of the action only.
    """
    login_url = None
    _rw()
    try:
        if action == "up":
            # If this node has never authenticated, `tailscale up` prints a login URL
            # and then blocks waiting for the browser flow — use a short timeout so
            # sh() falls into its TimeoutExpired branch and hands back the partial
            # output (which contains the URL) instead of just failing.
            rc, out = sh("tailscale", "up", "--accept-routes", timeout=12)
            m = re.search(r"https://login\.tailscale\.com/\S+", out)
            if m:
                login_url = m.group(0)
                rc = 0  # this is the expected first-run state, not a failure
        else:
            rc, out = sh("tailscale", "down", timeout=15)
    finally:
        _ro()
    return rc, out, login_url


async def tailscale_ctl(request):
    body = await request.json()
    action = body.get("action", "status")
    login_url = None
    if action in ("up", "down"):
        if sh("bash", "-c", "command -v tailscale")[0] != 0:   # cheap: stays inline
            return web.json_response({"ok": False, "error": "tailscale not installed — run install first"}, status=400)
        rc, out, login_url = await run_blocking(_tailscale_updown_blocking, action)
        # Tailnet state just changed → re-tune Janus ICE so remote WebRTC gains (up) or
        # loses (down) the tailscale0 candidate. Best-effort; never fail the up/down.
        try:
            await run_blocking(_janus_ice_tune_blocking)
        except Exception as _e:
            log.warning("janus ICE re-tune after tailscale %s failed: %s", action, _e)
    else:
        rc, out = await sh_a("tailscale", "status", timeout=10)
    resp = {"ok": rc == 0, "action": action, "detail": out[:1500]}
    if login_url:
        resp["login_url"] = login_url
    return web.json_response(resp)


WPA_CONF = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"


def _wifi_write_network(ssid, pw, priority=None):
    """Append (or replace) a network={} block for `ssid` with a PLAIN QUOTED psk.

    NOT wpa_passphrase: it was the root cause of a real outage (2026-07-17) — it
    fails silently/oddly on SSIDs containing spaces or punctuation (e.g. "Quality
    Inn- Office"), so the credentials never actually got written. wpa_supplicant
    accepts a plain quoted ASCII passphrase directly, no hashing step needed. See
    the same fix in provision/mb-portal.sh (captive-portal onboarding).
    """
    
    text = ""
    try:
        with open(WPA_CONF) as f:
            text = f.read()
    except FileNotFoundError:
        text = "ctrl_interface=/run/wpa_supplicant\nupdate_config=1\ncountry=US\n"
    # drop any existing block(s) for this SSID first, so re-adding/editing never duplicates
    text = re.sub(r'\nnetwork=\{[^}]*ssid="%s"[^}]*\}\n' % re.escape(ssid), "\n", text)
    if pw:
        prio = ("\n\tpriority=%d" % priority) if priority is not None else ""
        block = '\nnetwork={\n\tssid="%s"\n\tpsk="%s"%s\n}\n' % (ssid, pw, prio)
    else:
        block = '\nnetwork={\n\tssid="%s"\n\tkey_mgmt=NONE\n}\n' % ssid
    with open(WPA_CONF, "w") as f:
        f.write(text.rstrip() + "\n" + block)


async def wifi_connect(request):
    """POST /mb/net/wifi {ssid, password} — add/connect a Wi-Fi network via wpa_supplicant."""
    body = await request.json()
    ssid = (body.get("ssid") or "").strip()
    pw = body.get("password", "")
    if not ssid:
        return web.json_response({"ok": False, "error": "ssid required"}, status=400)
    if pw and len(pw) < 8:
        return web.json_response({"ok": False, "error": "password must be at least 8 characters"}, status=400)
    _rw()
    try:
        try:
            _wifi_write_network(ssid, pw)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        await sh_a("systemctl", "restart", "wpa_supplicant@wlan0")
    finally:
        _ro()
    cfg = load_config("net", {}); cfg["wifi"] = {"ssid": ssid}; save_config("net", cfg)
    return web.json_response({"ok": True, "ssid": ssid, "note": "added; may take a few seconds to associate"})


async def wifi_saved(_):
    """GET /mb/net/wifi/saved — list SSIDs currently saved in wpa_supplicant, plus which
    one (if any) wlan0 is associated to right now."""
    
    ssids = []
    try:
        with open(WPA_CONF) as f:
            text = f.read()
        ssids = re.findall(r'ssid="([^"]*)"', text)
    except FileNotFoundError:
        pass
    current = None
    rc, out = await sh_a("iw", "dev", "wlan0", "link", timeout=8)
    m = re.search(r"SSID:\s*(.+)", out)
    if m:
        current = m.group(1).strip()
    return web.json_response({"ok": True, "saved": ssids, "current": current})


async def wifi_forget(request):
    """POST /mb/net/wifi/forget {ssid} — remove a saved network block."""
    
    body = await request.json()
    ssid = (body.get("ssid") or "").strip()
    if not ssid:
        return web.json_response({"ok": False, "error": "ssid required"}, status=400)
    _rw()
    try:
        try:
            with open(WPA_CONF) as f:
                text = f.read()
        except FileNotFoundError:
            return web.json_response({"ok": False, "error": "no saved networks"}, status=404)
        new_text = re.sub(r'\nnetwork=\{[^}]*ssid="%s"[^}]*\}\n' % re.escape(ssid), "\n", text)
        if new_text == text:
            return web.json_response({"ok": False, "error": "SSID not found in saved networks"}, status=404)
        with open(WPA_CONF, "w") as f:
            f.write(new_text)
    finally:
        _ro()
    return web.json_response({"ok": True, "ssid": ssid})


async def wol(request):
    """POST /mb/net/wol {mac} — send a Wake-on-LAN magic packet (no external deps)."""
    import socket
    body = await request.json()
    mac = (body.get("mac") or "").strip()
    hexmac = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(hexmac) != 12:
        return web.json_response({"ok": False, "error": "invalid MAC"}, status=400)
    try:
        raw = bytes.fromhex(hexmac)
        packet = b"\xff" * 6 + raw * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(packet, ("255.255.255.255", port))
        s.close()
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)
    return web.json_response({"ok": True, "mac": mac})


async def wifi_scan(_):
    """GET /mb/net/wifi/scan — list nearby SSIDs (wpa_cli on PiKVM, nmcli fallback)."""
    nets = []
    rc, _o = await sh_a("wpa_cli", "-i", "wlan0", "scan", timeout=6)
    await asyncio.sleep(2)   # was time.sleep(2) — that blocked the whole event loop (bug G)
    rc, out = await sh_a("wpa_cli", "-i", "wlan0", "scan_results", timeout=8)
    if rc == 0 and out:
        for line in out.splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 5 and cols[4].strip():
                nets.append({"ssid": cols[4].strip(), "signal": cols[2].strip(),
                             "secure": "WPA" in cols[3] or "WEP" in cols[3]})
    if not nets:  # NetworkManager fallback
        rc, out = await sh_a("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", timeout=10)
        if rc == 0:
            for line in out.splitlines():
                p = line.split(":")
                if p and p[0]:
                    nets.append({"ssid": p[0], "signal": p[1] if len(p) > 1 else "",
                                 "secure": bool(len(p) > 2 and p[2] and p[2] != "--")})
    seen, uniq = set(), []
    for n in sorted(nets, key=lambda x: -int(x["signal"] or 0) if str(x["signal"]).lstrip("-").isdigit() else 0):
        if n["ssid"] not in seen:
            seen.add(n["ssid"]); uniq.append(n)
    return web.json_response({"ok": True, "networks": uniq[:30]})


async def update_check(_):
    """GET /mb/net/update — how many commits behind the DEPLOYED state we are. Compares
    the item-31 deployed-commit STAMP (not the clone HEAD) to origin, so a unit that
    pulled but never finished deploying is never reported 'up to date'. Classifies the
    pending diff as incremental (fast) vs full (structural files changed)."""
    # git fetch writes .git/FETCH_HEAD, which is on the read-only rootfs.
    _rw()
    # safe.directory inline, NOT `git config --global`: /root is on the read-only
    # rootfs so the global write always failed (noisy `$HOME not set` / RO-fs error),
    # and root owns the repo so no dubious-ownership check even fires.
    await sh_a("bash", "-c", "cd /opt/magicbridge && git -c safe.directory=/opt/magicbridge fetch origin main 2>&1", timeout=30)
    _ro()
    _rc, cur = sh("bash", "-c", "git -C /opt/magicbridge rev-parse --short HEAD 2>/dev/null")
    _rc, origin = sh("bash", "-c", "git -C /opt/magicbridge rev-parse origin/main 2>/dev/null")
    base = _read_stamp()   # what is actually DEPLOYED, not what the clone sits at
    if not base:
        # Nothing ever proved fully deployed → force a (re)install rather than risk a
        # fake up-to-date state (item 31).
        return web.json_response({"ok": True, "updates": 1, "update_available": True,
                                  "commits_behind": 0, "changed": 0, "mode": "full",
                                  "version": cur.strip(), "deployed": None, "branch": "main",
                                  "unverified": True,
                                  "detail": "deployment unverified → reinstall"})
    _rc, behind = sh("bash", "-c", "cd /opt/magicbridge && git rev-list --count %s..origin/main 2>/dev/null" % base)
    n = int(behind.strip()) if behind.strip().isdigit() else 0
    if n == 0:
        # Diverged (force-push/rebase): the stamp isn't an ancestor of origin, so the
        # count is 0 yet the two differ — still an update the unit needs.
        _rc, anc = sh("bash", "-c", "cd /opt/magicbridge && git merge-base --is-ancestor %s origin/main 2>/dev/null && echo yes || echo no" % base)
        _rc, sfull = sh("bash", "-c", "git -C /opt/magicbridge rev-parse %s 2>/dev/null" % base)
        if anc.strip() != "yes" and sfull.strip() and origin.strip() and sfull.strip() != origin.strip():
            n = 1
    _rc, changed = sh("bash", "-c", "cd /opt/magicbridge && git diff --name-only %s..origin/main 2>/dev/null | wc -l" % base)
    nchanged = int(changed.strip()) if changed.strip().isdigit() else 0
    _rc, struct = sh("bash", "-c", "cd /opt/magicbridge && git diff --name-only %s..origin/main 2>/dev/null "
                     "| grep -cE '^(systemd/|nginx/|magic-install.sh|kvmd-overrides/)'" % base)
    is_struct = struct.strip().isdigit() and int(struct.strip()) > 0
    # "What's new" (DIY D12): a plain one-line summary of EVERY pending commit, not
    # just the latest, so the operator sees exactly what an update will bring. Strip
    # the conventional-commit `type(scope):` prefix so it reads as plain English.
    whatsnew = []
    if n > 0:
        _rc, log = sh("bash", "-c",
                      "cd /opt/magicbridge && git log --no-merges --format=%%s %s..origin/main 2>/dev/null | head -40" % base)
        for line in log.splitlines():
            line = re.sub(r'^\s*[a-z]+(\([^)]*\))?!?:\s*', '', line.strip())
            if line:
                whatsnew.append(line)
    return web.json_response({"ok": True, "updates": n, "update_available": n > 0,
                              "commits_behind": n, "changed": nchanged,
                              "mode": ("full" if is_struct else "incremental"),
                              "version": cur.strip(), "deployed": base[:7], "branch": "main",
                              "unverified": False, "whatsnew": whatsnew,
                              "detail": ("%d update%s available" % (n, "" if n == 1 else "s")) if n else "up to date"})


async def logs_tail(request):
    """GET /mb/net/logs?unit=&n= — tail recent journald logs for our services."""
    unit = request.query.get("unit", "")
    n = request.query.get("n", "80")
    n = n if n.isdigit() else "80"
    args = ["journalctl", "-n", n, "--no-pager", "-o", "short-iso"]
    if unit in ("kvmd", "kvmd-nginx", "magicbridge-net", "magicbridge-stealth", "magicbridge-agent"):
        args += ["-u", unit]
    rc, out = await sh_a(*args, timeout=12)
    return web.json_response({"ok": rc == 0, "unit": unit or "all", "text": out[-8000:]})


def _rw():
    sh("bash", "-c", "command -v rw >/dev/null && rw || mount -o remount,rw /")


def _ro():
    # Always relock: fall back to a direct remount if the `ro` helper is absent,
    # symmetric with _rw() and mbcommon._fs (bug F — the old `|| true` could leave
    # the rootfs writable on any build without the helper).
    sh("bash", "-c", "command -v ro >/dev/null && ro || mount -o remount,ro /")


# ---- Janus ICE tuning: never offer a DEAD tailscale0 candidate (DIY A1) --------
# Janus gathers an ICE host candidate from EVERY up interface, tailscale0 included.
# tailscale0 stays UP even when the tailnet is OFFLINE, so that candidate is
# unreachable and every media send to it errors ("only sent -1 bytes?") — the browser
# never gets a frame, hits its connect timeout, and drops to MJPEG. Forever. This was
# the single biggest WebRTC bug on the DIY sibling.
#
# The nuance (do NOT just blacklist tailscale0 permanently): that kills low-latency
# remote WebRTC, which is exactly what the tailnet is for when you're off-LAN. Decide
# from LIVE tailnet state — allow tailscale0 when the tailnet is Running, skip it
# otherwise. kvmd-janus is restarted ONLY when the value actually flips.
JANUS_JCFG = "/etc/kvmd/janus/janus.jcfg"


def _tailnet_up() -> bool:
    import json
    rc, out = sh("tailscale", "status", "--json", timeout=8)
    if rc != 0 or not out.strip():
        return False
    try:
        d = json.loads(out)
    except Exception:
        return False
    # Running backend AND at least one assigned tailnet IP = a usable path.
    return d.get("BackendState") == "Running" and bool(d.get("TailscaleIPs"))


def _janus_ice_set(ignore: str) -> bool:
    """Set nat.ice_ignore_list in janus.jcfg to `ignore`. Returns True iff it changed."""
    try:
        txt = open(JANUS_JCFG).read()
    except OSError:
        return False
    cur = re.search(r'ice_ignore_list\s*=\s*"([^"]*)"', txt)
    if cur is not None:
        if cur.group(1) == ignore:
            return False                       # already correct: no write, no restart
        new = txt[:cur.start(1)] + ignore + txt[cur.end(1):]
    else:
        m = re.search(r'nat:\s*\{', txt)       # inject inside the nat { } block
        if not m:
            return False
        new = txt[:m.end()] + ('\n\tice_ignore_list = "%s"' % ignore) + txt[m.end():]
    _rw()
    try:
        tmp = JANUS_JCFG + ".mbtmp"            # atomic replace so a crash never truncates it
        with open(tmp, "w") as f:
            f.write(new); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, JANUS_JCFG)
    finally:
        _ro()
    return True


def _janus_ice_tune_blocking() -> bool:
    """Match janus ICE to tailnet state; restart kvmd-janus only on a real change."""
    ignore = "" if _tailnet_up() else "tailscale0"
    if _janus_ice_set(ignore):
        sh("systemctl", "restart", "kvmd-janus", timeout=25)
        return True
    return False


# ---- deployed-commit stamp (item 31) --------------------------------
# The web updater used to compare the git CLONE's HEAD to origin. A shutdown that
# landed mid-apply — after `git reset` had already advanced HEAD but before the
# deploy/restart finished — left HEAD == origin, so the check reported "up to date"
# while the unit ran OLD code, with no way to retry from the UI. Fix: the apply
# STAMPS the commit it fully deployed as its last success-only step, and the check
# compares THAT, never HEAD. A missing/garbage stamp forces "deployment unverified
# → reinstall", so a unit can never be trapped in a fake up-to-date state.
DEPLOY_STAMP = "/opt/magicbridge/.mb-deployed"


def _head_sha():
    _rc, sha = sh("bash", "-c", "git -C /opt/magicbridge rev-parse HEAD 2>/dev/null")
    return sha.strip()


def _read_stamp():
    """Return the fully-deployed commit SHA, or "" if the stamp is missing/garbage or
    points at a commit this clone doesn't have."""
    try:
        with open(DEPLOY_STAMP) as f:
            s = f.read().strip()
    except Exception:
        return ""
    if not re.fullmatch(r"[0-9a-f]{7,40}", s or ""):
        return ""
    _rc, ok = sh("bash", "-c", "git -C /opt/magicbridge cat-file -e %s^{commit} 2>/dev/null && echo ok" % s)
    return s if "ok" in ok else ""


def _write_stamp(sha):
    """Record the fully-deployed commit atomically. Success-only, LAST deploy step.
    Written inside the _rw() window; lives on the SD rootfs so it survives a reboot."""
    if not sha:
        return
    tmp = DEPLOY_STAMP + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(sha + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DEPLOY_STAMP)
    except Exception as e:
        log.warning("deploy stamp write failed: %s", e)


def _deploy_structural() -> bool:
    """Install + activate the structural bits that a plain `git reset` drops onto disk
    but never wires up — so the in-UI "Update" button is a COMPLETE upgrade (no
    magic-install needed for normal updates). Mirrors magic-install phase4/5/6.
    Idempotent; only called when structural files actually changed. Returns True on
    success so the caller withholds the item-31 stamp if the install failed.

    Covers: (1) unit files, (2) systemd DROP-INS under <unit>.service.d/ (e.g. the
    tailscaled PST-state fix), (3) the nginx block + kvmd override, (4) daemon-reload,
    (5) enabling our always-on units so a NEWLY-added one (e.g. mb-wifi-latency) turns
    on without a manual install. `[ -f X ] && cmd || true` is set -e-safe: a missing
    optional file skips, a real install failure aborts (fails the deploy).

    NOT done here (deliberately): rebuilding the USB gadget for an otg/msd override
    change — that briefly drops the target's keyboard/mouse, so it's left to a reboot
    (kvmd-otg builds the gadget fresh from the override at boot)."""
    rc, _out = sh("bash", "-c",
       'set -e; R=/opt/magicbridge; '
       # 1. unit files
       'for u in "$R"/systemd/*.service; do [ -e "$u" ] && install -Dm644 "$u" "/etc/systemd/system/$(basename "$u")"; done; '
       # 2. drop-ins: systemd/<unit>.service.d/*.conf -> /etc/systemd/system/<unit>.service.d/
       'for d in "$R"/systemd/*.service.d; do [ -d "$d" ] || continue; b="$(basename "$d")"; '
       '  for f in "$d"/*.conf; do [ -e "$f" ] && install -Dm644 "$f" "/etc/systemd/system/$b/$(basename "$f")"; done; done; '
       # 3. nginx block + kvmd override
       '[ -f "$R/nginx/magicbridge.conf" ] && install -Dm644 "$R/nginx/magicbridge.conf" /etc/kvmd/nginx/magicbridge.conf; '
       '[ -f "$R/kvmd-overrides/override.d/00-magicbridge.yaml" ] && install -Dm644 "$R/kvmd-overrides/override.d/00-magicbridge.yaml" /etc/kvmd/override.d/00-magicbridge.yaml; '
       'systemctl daemon-reload; '
       # 4. enable our always-on units (idempotent; picks up a NEW one like mb-wifi-latency).
       #    First-boot/portal units are intentionally NOT touched here.
       'for u in mb-wifi-latency mb-mdns-alias mb-anon-defaults magicbridge-net magicbridge-stealth magicbridge-agent; do '
       '  { [ -f "/etc/systemd/system/$u.service" ] && systemctl enable "$u.service" >/dev/null 2>&1; } || true; done; '
       # 5. start the Wi-Fi latency unit now so its fix applies without a reboot.
       '{ [ -f /etc/systemd/system/mb-wifi-latency.service ] && systemctl start mb-wifi-latency.service >/dev/null 2>&1; } || true',
       timeout=90)
    return rc == 0


# ---- EDID editor (kvmd-edidconf) -----------------------------------
async def edid_get(_):
    import re
    _rc, help_txt = await sh_a("kvmd-edidconf", "--help", timeout=10)
    m = re.search(r"--import-preset \{([^}]+)\}", help_txt)
    presets = [p.strip() for p in m.group(1).split("|")] if m else []
    _rc, cur = await sh_a("kvmd-edidconf", timeout=10)
    return web.json_response({"ok": True, "presets": presets, "current": cur[-2000:]})


async def edid_apply(request):
    body = await request.json()
    preset = body.get("preset", "")
    if not preset:
        return web.json_response({"ok": False, "error": "preset required"}, status=400)
    _rw()
    try:
        rc, out = await sh_a("kvmd-edidconf", "--import-preset", preset, "--apply", timeout=40)
    finally:
        _ro()
    return web.json_response({"ok": rc == 0, "preset": preset, "detail": out[-1500:]})


# ---- Realistic monitor spoofing (no PiKVM presets) ----------------
# Presents the target with a real-looking display identity via kvmd-edidconf's
# manufacturer/name/product/serial fields — Dell/LG/Samsung/etc., never "v4mini".
MONITORS = {
    "dell_u2720q":  {"label": "Dell U2720Q 27\" 4K",     "mfc": "DEL", "name": "DELL U2720Q",   "product": 16528},
    "dell_p2419h":  {"label": "Dell P2419H 24\"",         "mfc": "DEL", "name": "DELL P2419H",   "product": 16473},
    "lg_27gl850":   {"label": "LG UltraGear 27GL850",     "mfc": "GSM", "name": "LG ULTRAGEAR",  "product": 23450},
    "lg_24mp":      {"label": "LG 24MP60G",               "mfc": "GSM", "name": "LG 24MP60G",    "product": 22321},
    "samsung_g7":   {"label": "Samsung Odyssey G7",       "mfc": "SAM", "name": "Odyssey G7",    "product": 3420},
    "samsung_s24":  {"label": "Samsung S24R350",          "mfc": "SAM", "name": "S24R35x",       "product": 3654},
    "asus_vg279":   {"label": "ASUS VG279Q 27\"",         "mfc": "AUS", "name": "ASUS VG279",    "product": 10146},
    "hp_e24":       {"label": "HP E24 G4 24\"",           "mfc": "HWP", "name": "HP E24 G4",     "product": 13666},
    "benq_gw2480":  {"label": "BenQ GW2480",              "mfc": "BNQ", "name": "BenQ GW2480",   "product": 30760},
    "acer_kg241":   {"label": "Acer KG241Q",              "mfc": "ACR", "name": "Acer KG241Q",   "product": 2402},
    "generic_1080": {"label": "Generic 1080p Display",    "mfc": "GEN", "name": "Generic Display", "product": 4097},
}


async def monitor_get(_):
    rc, cur = await sh_a("kvmd-edidconf", timeout=10)
    return web.json_response({"ok": True,
        "monitors": {k: {"label": v["label"], "mfc": v["mfc"], "name": v["name"]} for k, v in MONITORS.items()},
        "current": cur[-1500:]})


def _realistic_monitor_serial(mfc):
    """A plausible ASCII display serial (max 13 chars) — never the CAFEBABE tell.
    Loosely mimics real vendor serial formats so the target reads a believable panel."""
    import random, string
    d = "".join(random.choices(string.digits, k=7))
    a = "".join(random.choices(string.ascii_uppercase, k=2))
    fmt = {
        "DEL": "CN%s%s" % ("".join(random.choices(string.digits, k=5)), a),   # Dell-ish
        "GSM": "%s%sLG" % (a, "".join(random.choices(string.digits, k=6))),   # LG
        "SAM": "H%sNZ" % "".join(random.choices(string.digits + string.ascii_uppercase, k=7)),  # Samsung
    }
    return (fmt.get(mfc) or (a + d))[:13]


def _edid_write_blocking(mfc, name, product, serial, mon_serial) -> tuple[int, str]:
    """rw -> kvmd-edidconf --apply (up to 45s over i2c) -> ro, offloaded as one batch
    (item 37). This writes the monitor identity the TARGET reads, so it must complete
    as a unit; inline it froze all input for the whole EDID write."""
    _rw()
    try:
        return sh("kvmd-edidconf", "--set-mfc-id", mfc, "--set-monitor-name", name,
                  "--set-product-id", str(product), "--set-serial", str(serial),
                  "--set-monitor-serial", mon_serial, "--apply", timeout=45)
    finally:
        _ro()


async def monitor_set(request):
    import random
    body = await request.json()
    m = MONITORS.get(body.get("preset", ""))
    if m:
        mfc, name, product = m["mfc"], m["name"], m["product"]
    else:
        mfc = (body.get("mfc") or "DEL")[:3].upper()
        name = body.get("name") or "Generic Display"
        product = int(str(body.get("product") or "4097"), 0)
    serial = random.randint(1000000, 99999999)
    mon_serial = _realistic_monitor_serial(mfc)   # ASCII DTD serial — replaces "CAFEBABE"
    rc, out = await run_blocking(_edid_write_blocking, mfc, name, product, serial, mon_serial)
    return web.json_response({"ok": rc == 0,
                              "applied": {"mfc": mfc, "name": name, "product": product,
                                          "serial": serial, "monitor_serial": mon_serial},
                              "detail": out[-1200:]})


# ---- VNC (kvmd-vnc) ------------------------------------------------
async def vnc_get(_):
    _rc, active = sh("systemctl", "is-active", "kvmd-vnc")
    _rc, enabled = sh("systemctl", "is-enabled", "kvmd-vnc")
    return web.json_response({"ok": True, "active": active.strip() == "active",
                              "enabled": "enabled" in enabled, "port": 5900})


VNC_WANTS = "/etc/systemd/system/multi-user.target.wants/kvmd-vnc.service"
VNC_UNIT = "/usr/lib/systemd/system/kvmd-vnc.service"


async def vnc_set(request):
    body = await request.json()
    on = bool(body.get("on"))
    # NOTE: `systemctl enable` fails with EROFS here even after remounting / rw —
    # its symlink write goes through a path that doesn't observe our remount. But a
    # plain os.symlink() under /etc DOES work after _rw() (same as writing the TOTP
    # secret), so we create the boot-persistence symlink ourselves and use plain
    # start/stop (which never touch disk) for the immediate action.
    _rw()
    try:
        if on:
            try:
                os.makedirs(os.path.dirname(VNC_WANTS), exist_ok=True)
                if not os.path.islink(VNC_WANTS):
                    os.symlink(VNC_UNIT, VNC_WANTS)
            except FileExistsError:
                pass
            except Exception as e:
                log.warning("vnc enable symlink: %s", e)
            rc, out = await sh_a("systemctl", "start", "kvmd-vnc", timeout=25)
        else:
            rc, out = await sh_a("systemctl", "stop", "kvmd-vnc", timeout=25)
            try:
                if os.path.islink(VNC_WANTS):
                    os.remove(VNC_WANTS)
            except Exception as e:
                log.warning("vnc disable symlink: %s", e)
    finally:
        _ro()
    active = sh("systemctl", "is-active", "kvmd-vnc")[0] == 0
    return web.json_response({"ok": (active == on), "on": on, "active": active,
                              "boot_persist": os.path.islink(VNC_WANTS), "detail": out[-800:]})


# ---- 2FA / TOTP (standard RFC-6238, no external deps) --------------
TOTP_SECRET = "/etc/kvmd/totp.secret"


def _totp(secret_b32, when=None, step=30, digits=6):
    import base64, hmac, struct, time as _t
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    counter = struct.pack(">Q", int((when or _t.time()) // step))
    dig = hmac.new(key, counter, "sha1").digest()
    off = dig[-1] & 0x0F
    code = (struct.unpack(">I", dig[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


async def totp_status(_):
    try:
        sec = open(TOTP_SECRET).read().strip()
    except Exception:
        sec = ""
    return web.json_response({"ok": True, "enabled": bool(sec)})


async def totp_generate(_):
    import base64, secrets
    sec = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    uri = "otpauth://totp/MagicBridgeV2:admin?secret=%s&issuer=MagicBridgeV2" % sec
    return web.json_response({"ok": True, "secret": sec, "uri": uri})


async def totp_enable(request):
    import time as _t
    body = await request.json()
    sec = (body.get("secret") or "").strip().replace(" ", "")
    code = str(body.get("code") or "").strip()
    if not sec or not code:
        return web.json_response({"ok": False, "error": "secret and code required"}, status=400)
    # Verify the user's authenticator matches BEFORE writing, so we never lock them out.
    if not any(_totp(sec, _t.time() + off) == code for off in (-30, 0, 30)):
        return web.json_response({"ok": False, "error": "code didn't match — re-check your authenticator app"}, status=400)
    _rw()
    try:
        with open(TOTP_SECRET, "w") as f:
            f.write(sec + "\n")
        sh("chown", "kvmd:kvmd", TOTP_SECRET)
        sh("chmod", "600", TOTP_SECRET)
    finally:
        _ro()
    return web.json_response({"ok": True, "enabled": True})


async def totp_disable(_):
    _rw()
    try:
        open(TOTP_SECRET, "w").close()
    finally:
        _ro()
    return web.json_response({"ok": True, "enabled": False})


# ---- Tailscale install + Funnel ------------------------------------
def _tailscale_install_blocking() -> tuple[bool, str, bool]:
    """The whole install sequence, run in ONE executor thread (item 37).

    PiKVM's rootfs is read-only by default. pacman needs to write to /var/lib/pacman
    and /usr, and `systemctl enable` needs to write a unit symlink under /etc — both
    fail silently-ish (non-zero rc, swallowed by the button) unless we unlock first.

    This is the worst blocker in the service: pacman (120s) plus a curl|sh fallback
    (180s) is up to ~5 minutes. Inline on the event loop that froze EVERY connected
    client's keyboard, mouse and status polling for the entire install.
    Returns (ok, detail, already_installed).
    """
    already = sh("bash", "-c", "command -v tailscale")[0] == 0
    if already and sh("systemctl", "is-enabled", "tailscaled")[0] == 0:
        return True, "tailscale already installed", True
    _rw()
    try:
        out = ""
        if not already:
            rc, out = sh("bash", "-c", "pacman -Sy --noconfirm tailscale 2>&1", timeout=120)
            if rc != 0:
                _rc2, out2 = sh("bash", "-c", "curl -fsSL https://tailscale.com/install.sh | sh 2>&1", timeout=180)
                out += "\n" + out2
        # PiKVM-specific fixes package, best-effort (not fatal if missing from the repos)
        sh("bash", "-c", "pacman -Sy --noconfirm tailscale-pikvm 2>&1", timeout=60)
        _rc_en, out_en = sh("systemctl", "enable", "--now", "tailscaled", timeout=20)
        out += "\n" + out_en
    finally:
        _ro()
    ok = (sh("bash", "-c", "command -v tailscale")[0] == 0
          and sh("systemctl", "is-active", "tailscaled")[0] == 0)
    return ok, out, False


async def tailscale_install(_):
    ok, detail, already = await run_blocking(_tailscale_install_blocking)
    if already:
        return web.json_response({"ok": True, "already": True, "detail": detail})
    return web.json_response({"ok": ok, "detail": detail[-1800:]})


async def tailscale_funnel(request):
    body = await request.json()
    on = bool(body.get("on", True))
    if sh("bash", "-c", "command -v tailscale")[0] != 0:
        return web.json_response({"ok": False, "error": "tailscale not installed — run install first"}, status=400)
    if on:
        rc, out = await sh_a("tailscale", "funnel", "--bg", "443", timeout=30)
        if rc != 0:
            rc, out = await sh_a("tailscale", "funnel", "443", "on", timeout=30)
    else:
        rc, out = await sh_a("tailscale", "funnel", "--https=443", "off", timeout=30)
        if rc != 0:
            rc, out = await sh_a("tailscale", "funnel", "443", "off", timeout=30)
    return web.json_response({"ok": rc == 0, "on": on, "detail": out[-1500:]})


async def led_get(_):
    """GET /mb/net/led — state of the board activity LED."""
    import glob
    leds = sorted(glob.glob("/sys/class/leds/*ACT*") + glob.glob("/sys/class/leds/led0"))
    on = None
    if leds:
        try:
            on = int(open(leds[0] + "/brightness").read().strip()) > 0
        except Exception:
            pass
    return web.json_response({"ok": True, "leds": [l.split("/")[-1] for l in leds], "on": on})


async def led_set(request):
    """POST /mb/net/led {on} — turn the board activity LED on/off (persist best-effort)."""
    import glob
    body = await request.json()
    on = bool(body.get("on"))
    leds = sorted(glob.glob("/sys/class/leds/*ACT*") + glob.glob("/sys/class/leds/led0"))
    if not leds:
        return web.json_response({"ok": False, "error": "no controllable LED found"}, status=404)
    d = leds[0]
    # detach the kernel trigger so brightness sticks, then set it
    sh("bash", "-c", "echo none > %s/trigger 2>/dev/null" % d)
    rc, out = sh("bash", "-c", "echo %d > %s/brightness" % (1 if on else 0, d))
    return web.json_response({"ok": rc == 0, "on": on, "led": d.split("/")[-1]})


def _update_deploy_blocking(prev: str) -> tuple[int, str, bool, bool]:
    """rw -> git fetch+reset (up to 90s) -> structural install (up to 60s) -> stamp -> ro.
    One offloaded batch (item 37): this is the longest operation the service performs,
    and inline it froze every client's keyboard/mouse for the whole update. The rw/ro
    window must also stay coherent in a single thread.
    Returns (rc, out, structural_needed, structural_ok)."""
    rc, out, struct, struct_ok = 1, "", False, True
    _rw()
    try:
        rc, out = sh("bash", "-c",
                     "cd /opt/magicbridge && "
                     "git -c safe.directory=/opt/magicbridge fetch origin main 2>&1 && "
                     "git -c safe.directory=/opt/magicbridge reset --hard origin/main 2>&1", timeout=90)
        if rc == 0:
            # Structural change since the last deploy? (systemd/nginx/kvmd-overrides
            # land on disk via git reset but are NOT active until re-installed.)
            if prev:
                _rc, s = sh("bash", "-c",
                            "cd /opt/magicbridge && git diff --name-only %s..HEAD 2>/dev/null "
                            "| grep -cE '^(systemd/|nginx/|magic-install.sh|kvmd-overrides/)'" % prev)
                struct = s.strip().isdigit() and int(s.strip()) > 0
            else:
                struct = True     # no known prior deploy → install structural bits to be safe
            if struct:
                struct_ok = _deploy_structural()
            # STAMP as the LAST deploy step, success-only, while the rootfs is still rw.
            # An apply interrupted before this point — OR a failed structural install —
            # leaves the OLD stamp, so update_check keeps offering the update instead of
            # falsely reporting up-to-date (item 31). Never stamp a half-deployed unit.
            if struct_ok:
                _write_stamp(_head_sha())
    finally:
        _ro()
    return rc, out, struct, struct_ok


async def update_apply(_):
    """POST /mb/net/update/apply — git-based self-update of /opt/magicbridge + restart sidecars."""
    oled = None
    start = time.monotonic()
    try:
        oled = subprocess.Popen(["/usr/local/bin/mb-oled-msg", "--updating"])  # OLED "Updating..." (handoff #19)
    except Exception:
        oled = None
    prev = _read_stamp()          # what was fully deployed before this apply
    rc, out, struct, struct_ok = await run_blocking(_update_deploy_blocking, prev)
    await sh_a("systemctl", "reload", "kvmd-nginx", timeout=15)
    # A tiny pull (e.g. a one-file VERSION bump) finishes in <1s, but kvmd-oled
    # needs ~2s just to paint one frame — so without a floor the "Updating..."
    # animation is killed before it ever appears. Hold the display long enough
    # for a human to actually see it (handoff #19 demo).
    OLED_MIN_VISIBLE = 5.0
    if oled:
        remaining = OLED_MIN_VISIBLE - (time.monotonic() - start)
        if remaining > 0:
            await asyncio.sleep(remaining)
    # Stop the OLED animation + hand the display back BEFORE we restart ourselves
    # (restarting magicbridge-net kills this handler, so do it here).
    if oled:
        try:
            oled.terminate()
        except Exception:
            pass
    await sh_a("bash", "-c", "/usr/local/bin/mb-oled-msg --resume")
    # Restart sidecars last; magicbridge-net restart ends this request.
    for svc in ("magicbridge-stealth", "magicbridge-agent", "magicbridge-net"):
        await sh_a("systemctl", "restart", svc, timeout=15)
    return web.json_response({"ok": rc == 0 and struct_ok, "structural": struct,
                              "structural_ok": struct_ok, "detail": out[-1500:]})


async def _on_startup(_app):
    # Apply the correct Janus ICE ignore-list for the CURRENT tailnet state at boot,
    # so a fresh/LAN unit never ships a dead tailscale0 candidate (DIY A1). Offloaded
    # so a slow `tailscale status` can't stall aiohttp startup; best-effort.
    try:
        await run_blocking(_janus_ice_tune_blocking)
    except Exception as _e:
        log.warning("janus ICE tune at startup failed: %s", _e)


def build_app():
    app = web.Application()
    app.on_startup.append(_on_startup)
    app.add_routes([
        web.get("/health", health),
        web.get("/sys", sysinfo),
        web.get("/status", status),
        web.post("/duckdns", duckdns_update),
        web.post("/lockdown", lockdown),
        web.post("/mac", mac_spoof),
        web.post("/tailscale", tailscale_ctl),
        web.post("/wifi", wifi_connect),
        web.get("/wifi/saved", wifi_saved),
        web.post("/wifi/forget", wifi_forget),
        web.get("/latency", net_latency),
        web.get("/clients", net_clients),
        web.get("/tailscale/peers", tailscale_peers),
        web.post("/wol", wol),
        web.get("/wifi/scan", wifi_scan),
        web.get("/update", update_check),
        web.post("/update/apply", update_apply),
        web.get("/led", led_get),
        web.post("/led", led_set),
        web.get("/logs", logs_tail),
        web.get("/edid", edid_get),
        web.post("/edid", edid_apply),
        web.get("/monitor", monitor_get),
        web.post("/monitor", monitor_set),
        web.get("/vnc", vnc_get),
        web.post("/vnc", vnc_set),
        web.get("/totp", totp_status),
        web.post("/totp/generate", totp_generate),
        web.post("/totp/enable", totp_enable),
        web.post("/totp/disable", totp_disable),
        web.post("/tailscale/install", tailscale_install),
        web.post("/tailscale/funnel", tailscale_funnel),
    ])
    return app


if __name__ == "__main__":
    log.info("magicbridge-net starting on 127.0.0.1:%d", PORT)
    web.run_app(build_app(), host="127.0.0.1", port=PORT, print=None)
