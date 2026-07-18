#!/usr/bin/env python3
"""
magicbridge-agent — MagicBridgeV2 AI agent + macro runner.

Turns natural language into actions on the target machine by asking an LLM for
a keystroke/paste plan, then executing it through kvmd's HID API (we reuse
kvmd's keyboard rather than touching the gadget ourselves).

Two big improvements over V1:
  1. API keys live SERVER-SIDE in /etc/magicbridge/agent.json (root-only),
     NOT in browser localStorage — closes V1's known plaintext-key gap.
  2. Every action goes through kvmd_client.hid_print, so paste speed, keymaps
     and jitter are handled by the proven native path.

Feature-flagged: disabled unless branding.env sets MB_AGENT_ENABLED=true (V1
parity — the agent tab stays hidden until you're ready).

Endpoints (behind kvmd nginx at /mb/agent/):
  GET  /health
  GET  /config              → providers configured (never returns key values)
  POST /config              → set provider + key (stored server-side)
  POST /run                 → {prompt} → plan → execute via kvmd HID
  GET  /macros              → list saved macros
  POST /macros              → save a macro {name, steps}
  POST /macros/run          → run a saved macro by name
"""
from __future__ import annotations
import os, sys, json, asyncio
sys.path.insert(0, "/opt/magicbridge/services/common")
try:
    from mbcommon import get_logger, load_config, save_config, load_branding
    from kvmd_client import kvmd
except Exception:
    import logging
    def get_logger(n): logging.basicConfig(level=logging.INFO); return logging.getLogger(n)
    def load_config(n, d=None): return dict(d or {})
    def save_config(n, d): pass
    def load_branding(): return {}
    def kvmd(): return None
from aiohttp import web

log = get_logger("mb-agent")
PORT = int(os.environ.get("MB_AGENT_PORT", "8412"))

PROVIDERS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai":     "https://api.openai.com/v1/chat/completions",
    "gemini":     "https://generativelanguage.googleapis.com/v1beta/models",
    "claude":     "https://api.anthropic.com/v1/messages",
}

SYSTEM_PROMPT = (
    "You are MagicBridge's remote-control agent. Convert the user's request into a "
    "JSON plan of steps to run on a remote PC via a USB keyboard. Return ONLY JSON: "
    '{"steps":[{"type":"text","value":"..."},{"type":"key","value":"enter"},'
    '{"type":"delay","ms":500}]}. Use "text" to type, "key" for single keys/combos, '
    '"delay" to wait. Keep it minimal and safe.'
)

def agent_enabled() -> bool:
    return str(load_branding().get("MB_AGENT_ENABLED", "false")).lower() == "true" \
        or load_config("agent", {}).get("enabled", False)

# ---- LLM plan (blocking call offloaded to executor) -----------------
def _ask_llm(provider: str, key: str, model: str, prompt: str) -> dict:
    import urllib.request
    url = PROVIDERS[provider]
    if provider == "claude":
        req = urllib.request.Request(url, method="POST", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        payload = {"model": model or "claude-sonnet-5", "max_tokens": 1024,
                   "system": SYSTEM_PROMPT, "messages": [{"role": "user", "content": prompt}]}
    else:
        req = urllib.request.Request(url, method="POST", headers={
            "Authorization": f"Bearer {key}", "content-type": "application/json"})
        payload = {"model": model or "gpt-4o-mini",
                   "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": prompt}]}
    with urllib.request.urlopen(req, data=json.dumps(payload).encode(), timeout=30) as r:
        data = json.loads(r.read().decode())
    # extract text across provider shapes
    if provider == "claude":
        txt = "".join(b.get("text", "") for b in data.get("content", []))
    else:
        txt = data["choices"][0]["message"]["content"]
    start, end = txt.find("{"), txt.rfind("}")
    return json.loads(txt[start:end + 1]) if start >= 0 else {"steps": []}

# Friendly key aliases → kvmd web key names (KeyboardEvent.code). kvmd's
# /hid/events/send_key + send_shortcut take these codes, so the agent's "key"
# steps now actually fire on the target (press Enter, Tab, combos like ctrl+c)
# instead of the old no-op TODO.
_KEYALIAS = {
    "enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
    "space": "Space", "spacebar": "Space", "backspace": "Backspace", "delete": "Delete", "del": "Delete",
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown", "insert": "Insert",
    "ctrl": "ControlLeft", "control": "ControlLeft", "shift": "ShiftLeft", "alt": "AltLeft",
    "win": "MetaLeft", "meta": "MetaLeft", "cmd": "MetaLeft", "super": "MetaLeft", "gui": "MetaLeft",
    "caps": "CapsLock", "capslock": "CapsLock", "printscreen": "PrintScreen",
    "minus": "Minus", "equal": "Equal", "comma": "Comma", "period": "Period", "slash": "Slash",
}

def _norm_key(s: str) -> str:
    s = str(s or "").strip()
    low = s.lower()
    if low in _KEYALIAS:
        return _KEYALIAS[low]
    if len(s) == 1 and s.isalpha():
        return "Key" + s.upper()
    if len(s) == 1 and s.isdigit():
        return "Digit" + s
    if len(low) >= 2 and low[0] == "f" and low[1:].isdigit():
        return "F" + low[1:]
    return s  # assume already a kvmd web key name (Enter, KeyA, ControlLeft, …)

async def _execute(plan: dict) -> list:
    results = []
    k = kvmd()
    for step in plan.get("steps", []):
        t = step.get("type")
        if t == "text" and k:
            r = await k.hid_print(step.get("value", ""))
            results.append({"text": step.get("value", "")[:40], "ok": r.get("ok")})
        elif t == "key" and k:
            val = str(step.get("value", "")).strip()
            # "ctrl+c" / "alt+F4" → chord via send_shortcut; single key → send_key
            parts = [p for p in val.replace(" ", "").split("+") if p]
            if len(parts) > 1:
                r = await k.hid_shortcut([_norm_key(p) for p in parts])
            elif parts:
                r = await k.hid_key(_norm_key(parts[0]))
            else:
                r = {"ok": False}
            results.append({"key": val, "ok": r.get("ok")})
        elif t == "delay":
            await asyncio.sleep(min(step.get("ms", 0) / 1000.0, 10))
            results.append({"delay_ms": step.get("ms")})
    return results

# ---- handlers -------------------------------------------------------
async def health(_): return web.json_response({"ok": True, "service": "magicbridge-agent",
                                                "enabled": agent_enabled()})

async def get_config(_):
    cfg = load_config("agent", {})
    # never leak key values
    provs = {p: bool(cfg.get("keys", {}).get(p)) for p in PROVIDERS}
    return web.json_response({"enabled": agent_enabled(), "active": cfg.get("provider"),
                              "model": cfg.get("model"), "providers_configured": provs})

async def set_config(request: web.Request):
    body = await request.json()
    cfg = load_config("agent", {})
    cfg.setdefault("keys", {})
    if body.get("provider"): cfg["provider"] = body["provider"]
    if body.get("model"):    cfg["model"] = body["model"]
    if body.get("provider") and body.get("key"):
        cfg["keys"][body["provider"]] = body["key"]     # stored root-only, server-side
    if "enabled" in body:    cfg["enabled"] = bool(body["enabled"])
    save_config("agent", cfg)                            # /etc/magicbridge/agent.json (0600)
    return web.json_response({"ok": True})

async def run(request: web.Request):
    if not agent_enabled():
        return web.json_response({"ok": False, "error": "agent disabled"}, status=403)
    body = await request.json()
    cfg = load_config("agent", {})
    provider = cfg.get("provider"); key = cfg.get("keys", {}).get(provider or "")
    if not provider or not key:
        return web.json_response({"ok": False, "error": "no provider/key configured"}, status=400)
    loop = asyncio.get_running_loop()
    try:
        plan = await loop.run_in_executor(None, _ask_llm, provider, key, cfg.get("model", ""), body.get("prompt", ""))
    except Exception as e:
        return web.json_response({"ok": False, "error": f"llm: {e}"}, status=502)
    results = await _execute(plan)
    return web.json_response({"ok": True, "plan": plan, "results": results})

async def list_macros(_):
    return web.json_response({"macros": load_config("macros", {}).get("items", [])})

async def save_macro(request: web.Request):
    body = await request.json()
    m = load_config("macros", {}); m.setdefault("items", [])
    m["items"] = [x for x in m["items"] if x.get("name") != body.get("name")]
    m["items"].append({"name": body["name"], "steps": body.get("steps", [])})
    save_config("macros", m)
    return web.json_response({"ok": True, "count": len(m["items"])})

async def run_macro(request: web.Request):
    body = await request.json()
    m = load_config("macros", {}).get("items", [])
    macro = next((x for x in m if x.get("name") == body.get("name")), None)
    if not macro:
        return web.json_response({"ok": False, "error": "macro not found"}, status=404)
    results = await _execute({"steps": macro["steps"]})
    return web.json_response({"ok": True, "results": results})

def build_app() -> web.Application:
    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.get("/config", get_config),
        web.post("/config", set_config),
        web.post("/run", run),
        web.get("/macros", list_macros),
        web.post("/macros", save_macro),
        web.post("/macros/run", run_macro),
    ])
    return app

if __name__ == "__main__":
    log.info("magicbridge-agent starting on 127.0.0.1:%d (enabled=%s)", PORT, agent_enabled())
    web.run_app(build_app(), host="127.0.0.1", port=PORT, print=None)
