"""
kvmd_client — thin async client for the local kvmd HTTP API.

This is how MagicBridgeV2 REUSES everything PiKVM already does well instead of
re-implementing it: ATX power, virtual media (MSD), HID paste, GPIO, streamer
snapshots, and system info all come straight from kvmd. Our sidecars and UI
call these helpers rather than talking to hardware directly.

kvmd listens on localhost (behind its own nginx on :443). We authenticate with
the header pair kvmd accepts for internal calls (X-KVMD-User / X-KVMD-Passwd),
read from /etc/magicbridge/kvmd.json (falls back to the PiKVM defaults).

All calls are defensive: on any failure they return {"ok": False, "error": ...}
so a missing kvmd (e.g. dev machine, or a renamed endpoint on a given OS build)
never crashes a caller. Endpoint paths are centralised so on-device bring-up can
adjust them in one place.
"""
from __future__ import annotations
import ssl, json, asyncio
from typing import Any
try:
    import aiohttp
except Exception:  # dev machines without aiohttp
    aiohttp = None

from mbcommon import load_config, get_logger  # type: ignore

log = get_logger("kvmd-client")

DEFAULTS = {
    "base": "https://127.0.0.1/api",
    "user": "admin",
    "passwd": "admin",
    "verify_tls": False,
}

class KvmdClient:
    def __init__(self, cfg: dict | None = None):
        c = {**DEFAULTS, **(cfg or load_config("kvmd", {}))}
        self.base = c["base"].rstrip("/")
        self._headers = {"X-KVMD-User": c["user"], "X-KVMD-Passwd": c["passwd"]}
        self._verify = bool(c.get("verify_tls"))

    def _ssl(self):
        if self._verify:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _req(self, method: str, path: str, **kw) -> dict[str, Any]:
        if aiohttp is None:
            return {"ok": False, "error": "aiohttp unavailable"}
        url = f"{self.base}{path}"
        try:
            timeout = aiohttp.ClientTimeout(total=kw.pop("timeout", 12))
            async with aiohttp.ClientSession(timeout=timeout, headers=self._headers) as s:
                async with s.request(method, url, ssl=self._ssl(), **kw) as r:
                    text = await r.text()
                    try:
                        data = json.loads(text)
                    except Exception:
                        data = {"raw": text}
                    return {"ok": r.status < 400, "status": r.status, "data": data}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- system ------------------------------------------------------
    async def info(self) -> dict:            return await self._req("GET", "/info")
    async def health(self) -> dict:          return await self._req("GET", "/info")

    # ---- ATX power (native PiKVM hardware power control) --------------
    async def atx_state(self) -> dict:       return await self._req("GET", "/atx")
    async def atx_power(self, action: str) -> dict:
        # action: on | off | off_hard | reset_hard
        return await self._req("POST", f"/atx/power?action={action}")
    async def atx_click(self, button: str) -> dict:
        # button: power | power_long | reset
        return await self._req("POST", f"/atx/click?button={button}")

    # ---- Mass Storage Drive (mount ISO / boot from virtual USB) -------
    async def msd_state(self) -> dict:       return await self._req("GET", "/msd")
    async def msd_set_params(self, image: str, cdrom: bool = True) -> dict:
        return await self._req("POST", f"/msd/set_params?image={image}&cdrom={int(cdrom)}")
    async def msd_connect(self, connected: bool = True) -> dict:
        return await self._req("POST", f"/msd/set_connected?connected={int(connected)}")

    # ---- HID (reuse kvmd's keyboard for paste / key events) ----------
    async def hid_state(self) -> dict:       return await self._req("GET", "/hid")
    async def hid_print(self, text: str, limit: int = 0, keymap: str = "en-us") -> dict:
        # kvmd types the given text on the target — used by the AI agent + macros.
        params = f"?limit={limit}&keymap={keymap}"
        return await self._req("POST", f"/hid/print{params}", data=text.encode("utf-8"))
    async def hid_set_keyboard(self, enabled: bool) -> dict:
        return await self._req("POST", f"/hid/set_params?keyboard_output={'usb' if enabled else ''}")
    async def hid_key(self, key: str) -> dict:
        # single key press+release (key = web KeyboardEvent.code, e.g. "Enter", "KeyA")
        import urllib.parse
        return await self._req("POST", f"/hid/events/send_key?key={urllib.parse.quote(key)}")
    async def hid_shortcut(self, keys: list[str]) -> dict:
        # chord: press all in order, release in reverse (e.g. ["ControlLeft","KeyC"])
        import urllib.parse
        q = urllib.parse.quote(",".join(keys))
        return await self._req("POST", f"/hid/events/send_shortcut?keys={q}")

    # ---- GPIO (LEDs, custom relays, WOL trigger channels) ------------
    async def gpio_state(self) -> dict:      return await self._req("GET", "/gpio")
    async def gpio_switch(self, channel: str, state: bool) -> dict:
        return await self._req("POST", f"/gpio/switch?channel={channel}&state={int(state)}")
    async def gpio_pulse(self, channel: str) -> dict:
        return await self._req("POST", f"/gpio/pulse?channel={channel}")

    # ---- Streamer (snapshot / params) --------------------------------
    async def streamer_state(self) -> dict:  return await self._req("GET", "/streamer")
    async def snapshot(self) -> dict:        return await self._req("GET", "/streamer/snapshot?allow_offline=1")


# convenience singleton
_default: KvmdClient | None = None
def kvmd() -> KvmdClient:
    global _default
    if _default is None:
        _default = KvmdClient()
    return _default
