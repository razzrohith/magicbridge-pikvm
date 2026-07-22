#!/usr/bin/env python3
"""
magicbridge-stealth — MagicBridgeV2 USB identity / stealth service.

Ports MagicBridge V1's signature feature onto the PiKVM base. kvmd builds the
USB gadget from its `otg:` config; we never edit kvmd's own files — instead we
write an override snippet at /etc/kvmd/override.d/90-magicbridge-otg.yaml and
ask kvmd to rebuild the gadget (systemctl restart kvmd-otg). This keeps us
forward-compatible with kvmd upgrades.

Endpoints (behind kvmd nginx at /mb/stealth/):
  GET  /health
  GET  /identity            → current identity + available presets
  POST /identity            → apply {preset|custom fields}; rebuilds gadget
  POST /serial/random       → randomise serial only
  POST /safe-mode           → {on} minimise exposed interfaces
  GET  /status              → gadget + kvmd-otg service state

WARNING carried from the migration plan: live gadget rebuild fights the
read-only rootfs. We toggle rw only for the write, restore ro, then restart
kvmd-otg. On real hardware, validate the rebind doesn't drop an active session.
"""
from __future__ import annotations
import os, sys, json, random, string, subprocess, asyncio, hashlib, hmac as _hmac, secrets as _secrets, time
from pathlib import Path
sys.path.insert(0, "/opt/magicbridge/services/common")
try:
    from mbcommon import get_logger, load_config, save_config
except Exception:
    import logging
    def get_logger(n): logging.basicConfig(level=logging.INFO); return logging.getLogger(n)
    def load_config(n, d=None): return dict(d or {})
    def save_config(n, d): pass
from aiohttp import web

log = get_logger("mb-stealth")
PORT = int(os.environ.get("MB_STEALTH_PORT", "8411"))
OTG_OVERRIDE = Path("/etc/kvmd/override.d/90-magicbridge-otg.yaml")

# Presets carry the V1 "verified" flag: True only where checked against a real
# device descriptor. Unverified ones are researched but not hardware-confirmed.
# Real keyboard+mouse combo receivers — devices that legitimately expose BOTH a
# keyboard and a mouse interface (so the composite HID gadget looks native).
# NOTHING here says "KVM", "composite", "PiKVM" or "MagicBridge" — those are tells.
PRESETS = {
    "logitech_unifying": {
        "label": "Logitech Unifying Receiver", "verified": True,
        "vendor_id": 0x046D, "product_id": 0xC52B,
        "manufacturer": "Logitech", "product": "USB Receiver",
    },
    "logitech_mk270": {
        "label": "Logitech MK270 Combo", "verified": False,
        "vendor_id": 0x046D, "product_id": 0xC534,
        "manufacturer": "Logitech", "product": "USB Receiver",
    },
    "microsoft_combo": {
        "label": "Microsoft Wireless Desktop", "verified": False,
        "vendor_id": 0x045E, "product_id": 0x0800,
        "manufacturer": "Microsoft", "product": "Microsoft USB Dual Receiver",
    },
    "dell_km636": {
        "label": "Dell KM636 Wireless Combo", "verified": False,
        "vendor_id": 0x413C, "product_id": 0x2110,
        "manufacturer": "Dell", "product": "Dell KM636 Receiver",
    },
    "hp_combo": {
        "label": "HP Wireless Keyboard & Mouse", "verified": False,
        "vendor_id": 0x03F0, "product_id": 0x134A,
        "manufacturer": "HP", "product": "HP Wireless Receiver",
    },
}

def rand_serial(n: int = 8) -> str:
    return "".join(random.choices(string.hexdigits.upper(), k=n))

def _clean_usb_str(v, fallback: str = "") -> str:
    """Sanitize a user-supplied USB string descriptor (manufacturer/product/serial)
    before it goes into the kvmd OTG YAML override. Strips control characters and the
    two characters that would break a double-quoted YAML scalar (`"` and `\\`), and
    caps length at the USB string-descriptor max (126). Without this, a stray quote or
    newline in a CUSTOM identity produces malformed YAML that fails the gadget rebuild
    and leaves the target's USB keyboard/mouse dead until the override is hand-removed."""
    s = str(v if v is not None else "")
    s = "".join(ch for ch in s if ch >= " " and ch not in '"\\').strip()
    return s[:126] or fallback

def _sh(*args, timeout=20) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:
        return 1, str(e)

def _fs(mode: str):
    # PiKVM read-only rootfs toggle
    _sh("bash", "-c", "command -v rw >/dev/null && %s || mount -o remount,%s /" %
        (mode, "rw" if mode == "rw" else "ro"))

def write_otg_override(ident: dict, hide_msd: bool = False) -> None:
    """Write our OTG override snippet (rw window kept as small as possible).

    Always emits a REALISTIC serial. kvmd's built-in default is the string
    "CAFEBABE" (a well-known magic number) whenever the serial is absent/empty —
    an obvious "this is a fake gadget" tell — so we never leave it unset. Mutates
    ident['serial'] in place so the caller persists the value it actually applied.

    hide_msd (safe-mode): remove the USB mass-storage function from the gadget. A
    real Logitech USB Receiver has NO mass-storage interface, so presenting one
    (kvmd's virtual media) is the single remaining "this isn't a real receiver"
    tell to a curious target. With it hidden the gadget is a pure keyboard+mouse
    receiver. Trade-off: virtual media (mounting an ISO to the target) is
    unavailable until safe-mode is turned back off. kvmd builds the mass-storage
    function ONLY when `kvmd.msd.type == "otg"` (see kvmd/apps/otg: `if
    config.kvmd.msd.type == "otg"`), so setting it to "disabled" is what actually
    drops the interface — verified on-device that the earlier
    `otg.devices.msd.default.enabled` key was silently ignored.
    """
    serial = _clean_usb_str(ident.get("serial"))
    if not serial or serial.upper() == "CAFEBABE":
        serial = rand_serial()
    ident["serial"] = serial
    # Sanitize the string descriptors at this single choke point — every path
    # (set_identity/random_serial/safe_mode/restore) funnels through here, so bad
    # input can never reach the YAML regardless of caller. Fallbacks are the safe
    # default receiver identity so a fully-stripped value degrades gracefully.
    manufacturer = _clean_usb_str(ident.get("manufacturer"), "Logitech")
    product = _clean_usb_str(ident.get("product"), "USB Receiver")
    body = (
        "otg:\n"
        f"    vendor_id: 0x{ident['vendor_id']:04X}\n"
        f"    product_id: 0x{ident['product_id']:04X}\n"
        f"    manufacturer: \"{manufacturer}\"\n"
        f"    product: \"{product}\"\n"
        f"    serial: \"{serial}\"\n"
    )
    if hide_msd:
        # Top-level kvmd: section (NOT under otg:). kvmd-otg only adds the
        # mass_storage function when kvmd.msd.type == "otg"; "disabled" drops it.
        body += (
            "kvmd:\n"
            "    msd:\n"
            "        type: disabled\n"
        )
    _fs("rw")
    try:
        OTG_OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
        OTG_OVERRIDE.write_text(body)
    finally:
        _fs("ro")


def _hide_msd() -> bool:
    """Single source of truth: hide the MSD interface whenever safe-mode is on."""
    return bool(current_identity().get("safe_mode", False))

_GADGET = "/sys/kernel/config/usb_gadget/kvmd"
_OTG_TEARDOWN = (
    'G=%s; if [ -d "$G" ]; then echo "" > $G/UDC 2>/dev/null; '
    'for c in $G/configs/*/; do for l in "$c"*; do [ -L "$l" ] && rm -f "$l"; done; '
    'for s in "$c"strings/*/; do rmdir "$s" 2>/dev/null; done; rmdir "$c" 2>/dev/null; done; '
    'for f in $G/functions/*/; do rmdir "$f" 2>/dev/null; done; '
    'for s in $G/strings/*/; do rmdir "$s" 2>/dev/null; done; rmdir $G 2>/dev/null; fi; '
    'rm -rf /run/kvmd/otg'
) % _GADGET


def rebuild_gadget() -> tuple[bool, str]:
    # kvmd-otg can't create the gadget on top of a running/leftover one, and its
    # own `stop` doesn't reliably remove the configfs gadget or /run/kvmd/otg — so
    # we tear BOTH down ourselves, then start fresh. This is what makes live USB
    # identity spoofing actually apply (a plain restart errors FileExists).
    _sh("systemctl", "reset-failed", "kvmd-otg")
    _sh("systemctl", "stop", "kvmd-otg", timeout=20)
    time.sleep(1)
    _sh("bash", "-c", _OTG_TEARDOWN)
    _sh("systemctl", "reset-failed", "kvmd-otg")
    rc, out = _sh("systemctl", "start", "kvmd-otg", timeout=25)
    if rc != 0:  # never leave the gadget down — clean once more + retry
        _sh("bash", "-c", _OTG_TEARDOWN)
        _sh("systemctl", "reset-failed", "kvmd-otg")
        rc, out = _sh("systemctl", "start", "kvmd-otg", timeout=25)
    if rc == 0:
        _sh("systemctl", "try-restart", "kvmd")
    return rc == 0, out

def current_identity() -> dict:
    return load_config("stealth", {
        "preset": "logitech_unifying", **PRESETS["logitech_unifying"],
        "serial": "", "safe_mode": False,  # Logitech Unifying legitimately has no serial
    })

# ---- separate stealth password (independent of the kvmd login) ------
# Gates the USB-identity actions with a second password, so someone with a live
# kvmd session still can't silently reflash the gadget identity. Hash+salt only.
def _hash_pw(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()

def _pw_cfg() -> dict:
    return load_config("stealth_auth", {})

def _check_pw(body: dict) -> bool:
    cfg = _pw_cfg()
    if not cfg.get("hash"):
        return True  # no gate configured → open
    return _hmac.compare_digest(_hash_pw(str(body.get("password", "")), cfg.get("salt", "")), cfg["hash"])

def _locked_response():
    return web.json_response({"ok": False, "locked": True, "error": "stealth password required"}, status=403)

async def lock_status(_):
    return web.json_response({"ok": True, "password_set": bool(_pw_cfg().get("hash"))})

# ---- brute-force lockout for the stealth gate ----------------------------
# Per-IP failed-attempt tracking with escalating temporary lockout. In-memory
# (resets on service restart, which is fine — an attacker can't restart it), so
# no disk writes on the read-only rootfs. nginx sets X-Real-IP for us.
_UNLOCK_FAILS: dict = {}          # ip -> [fail_count, locked_until_epoch]
_LOCK_AFTER = 5                   # free attempts before lockout kicks in
_LOCK_MAX = 900                   # cap a single lockout at 15 min

def _client_ip(request: web.Request) -> str:
    return request.headers.get("X-Real-IP") or (request.remote or "?")

async def unlock(request: web.Request):
    ip = _client_ip(request)
    now = time.time()
    fc, until = _UNLOCK_FAILS.get(ip, (0, 0.0))
    if now < until:
        wait = int(until - now)
        return web.json_response({"ok": False, "locked_out": True, "retry_after": wait,
                                  "error": f"too many attempts — locked for {wait}s"}, status=429)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if _check_pw(body):
        _UNLOCK_FAILS.pop(ip, None)          # success clears the record
        return web.json_response({"ok": True})
    fc += 1
    lock = 0
    if fc >= _LOCK_AFTER:                     # 15s, 30s, 60s, … doubling, capped
        lock = min(_LOCK_MAX, 15 * (2 ** (fc - _LOCK_AFTER)))
    _UNLOCK_FAILS[ip] = (fc, now + lock)
    resp = {"ok": False, "attempts": fc}
    if lock:
        resp.update(locked_out=True, retry_after=int(lock),
                    error=f"too many attempts — locked for {int(lock)}s")
    return web.json_response(resp, status=(429 if lock else 200))

async def set_password(request: web.Request):
    body = await request.json()
    new = str(body.get("password", ""))
    if len(new) < 4:
        return web.json_response({"ok": False, "error": "password too short (min 4 chars)"}, status=400)
    cfg = _pw_cfg()
    if cfg.get("hash") and not _hmac.compare_digest(_hash_pw(str(body.get("current", "")), cfg.get("salt", "")), cfg["hash"]):
        return web.json_response({"ok": False, "error": "current password incorrect"}, status=403)
    salt = _secrets.token_hex(8)
    save_config("stealth_auth", {"salt": salt, "hash": _hash_pw(new, salt)})
    return web.json_response({"ok": True})

# ---- handlers -------------------------------------------------------
async def health(_): return web.json_response({"ok": True, "service": "magicbridge-stealth"})

def _live_gadget_serial():
    """The serial the target actually sees right now (configfs) — source of truth."""
    try:
        return open("/sys/kernel/config/usb_gadget/kvmd/strings/0x409/serialnumber").read().strip()
    except Exception:
        return ""


async def get_identity(_):
    cur = current_identity()
    live = _live_gadget_serial()
    if live:  # reflect what's actually applied, not just the last saved config
        cur = {**cur, "serial": live}
    return web.json_response({
        "current": cur,
        "presets": {k: {"label": v["label"], "verified": v["verified"]} for k, v in PRESETS.items()},
    })

async def set_identity(request: web.Request):
    body = await request.json()
    if not _check_pw(body):
        return _locked_response()
    cur = current_identity()
    if body.get("preset") in PRESETS:
        ident = {**PRESETS[body["preset"]], "preset": body["preset"]}
    else:  # custom fields
        # Parse the IDs defensively: a non-numeric or out-of-range vendor/product id
        # used to raise here (outside the try/except below) and 500 the request.
        try:
            vid = int(str(body.get("vendor_id", cur["vendor_id"])), 0)
            pid = int(str(body.get("product_id", cur["product_id"])), 0)
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "vendor_id/product_id must be numeric (e.g. 0x046D)"}, status=200)
        if not (0 <= vid <= 0xFFFF and 0 <= pid <= 0xFFFF):
            return web.json_response({"ok": False, "error": "vendor_id/product_id must be 16-bit (0x0000-0xFFFF)"}, status=200)
        ident = {
            "preset": "custom",
            "label": body.get("label", "Custom"),
            "verified": False,
            "vendor_id": vid,
            "product_id": pid,
            "manufacturer": body.get("manufacturer", cur["manufacturer"]),
            "product": body.get("product", cur["product"]),
        }
    ident["serial"] = body.get("serial") or (rand_serial() if body.get("random_serial") else cur.get("serial", rand_serial()))
    ident["safe_mode"] = cur.get("safe_mode", False)

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, write_otg_override, ident, ident.get("safe_mode", False))
        ok, out = await loop.run_in_executor(None, rebuild_gadget)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"gadget apply failed: {e}"}, status=200)
    save_config("stealth", ident)
    return web.json_response({"ok": ok, "applied": ident, "detail": out[:1000]})

async def random_serial(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not _check_pw(body):
        return _locked_response()
    cur = current_identity(); cur["serial"] = rand_serial()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, write_otg_override, cur, cur.get("safe_mode", False))
        ok, out = await loop.run_in_executor(None, rebuild_gadget)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"gadget apply failed: {e}"}, status=200)
    save_config("stealth", cur)
    return web.json_response({"ok": ok, "serial": cur["serial"], "detail": out[:500]})

RANDOM_VENDORS = [("0x046d", "Logitech"), ("0x045e", "Microsoft"), ("0x413c", "Dell"),
                  ("0x1bcf", "Sunplus"), ("0x0951", "Kingston"), ("0x30fa", "Generic"),
                  ("0x1c4f", "SiGma"), ("0x093a", "Pixart")]
RANDOM_PRODUCTS = ["USB Receiver", "Composite Device", "HID Keyboard", "Wireless Receiver",
                   "USB Input Device", "Optical Mouse", "Multimedia Keyboard"]


async def randomize(request: web.Request):
    """POST /mb/stealth/randomize — spoof a fresh random USB identity + serial in one shot."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not _check_pw(body):
        return _locked_response()
    vid, mfr = random.choice(RANDOM_VENDORS)
    ident = {
        "preset": "random", "label": "Randomized identity", "verified": False,
        "vendor_id": int(vid, 0), "product_id": random.randint(0x1000, 0xFFFF),
        "manufacturer": mfr, "product": random.choice(RANDOM_PRODUCTS),
        "serial": rand_serial(), "safe_mode": current_identity().get("safe_mode", False),
    }
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, write_otg_override, ident, ident.get("safe_mode", False))
        ok, out = await loop.run_in_executor(None, rebuild_gadget)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"gadget apply failed: {e}"}, status=200)
    save_config("stealth", ident)
    return web.json_response({"ok": ok, "applied": ident, "detail": out[:500]})


async def backup(_):
    """GET /mb/stealth/backup — export MagicBridge config for safekeeping."""
    return web.json_response({"ok": True, "ts": int(time.time()), "config": {
        "net": load_config("net", {}), "stealth": load_config("stealth", {}),
    }})


async def restore(request: web.Request):
    """POST /mb/stealth/restore {config} — restore an exported config."""
    body = await request.json()
    if not _check_pw(body):
        return _locked_response()
    cfg = body.get("config", {})
    if isinstance(cfg.get("net"), dict):
        save_config("net", cfg["net"])
    if isinstance(cfg.get("stealth"), dict):
        save_config("stealth", cfg["stealth"])
    return web.json_response({"ok": True, "restored": list(cfg.keys())})


async def safe_mode(request: web.Request):
    """POST /mb/stealth/safe-mode {on} — minimise the exposed USB gadget.

    ON removes the mass-storage interface so the target sees a pure keyboard+mouse
    receiver (a real Logitech USB Receiver has no mass storage — this closes that
    tell). Applies LIVE by rewriting the OTG override + rebuilding the gadget.
    Trade-off, surfaced to the caller: virtual media is unavailable while ON.
    """
    body = await request.json()
    if not _check_pw(body):
        return _locked_response()
    on = bool(body.get("on"))
    cur = current_identity(); cur["safe_mode"] = on
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, write_otg_override, cur, on)
        ok, out = await loop.run_in_executor(None, rebuild_gadget)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"gadget apply failed: {e}"}, status=200)
    save_config("stealth", cur)
    return web.json_response({
        "ok": ok, "safe_mode": on,
        "note": ("MSD interface hidden — virtual media is off until safe-mode is disabled"
                 if on else "MSD interface restored — virtual media available"),
        "detail": out[:500]})

async def status(_):
    rc, out = _sh("systemctl", "is-active", "kvmd-otg")
    return web.json_response({"kvmd_otg": out.strip(), "identity": current_identity(),
                              "override_present": OTG_OVERRIDE.exists()})

def build_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.get("/identity", get_identity),
        web.post("/identity", set_identity),
        web.post("/serial/random", random_serial),
        web.post("/randomize", randomize),
        web.get("/backup", backup),
        web.post("/restore", restore),
        web.post("/safe-mode", safe_mode),
        web.get("/status", status),
        web.get("/lock-status", lock_status),
        web.post("/unlock", unlock),
        web.post("/password", set_password),
    ])
    return app

if __name__ == "__main__":
    log.info("magicbridge-stealth starting on 127.0.0.1:%d", PORT)
    web.run_app(build_app(), host="127.0.0.1", port=PORT, print=None)
