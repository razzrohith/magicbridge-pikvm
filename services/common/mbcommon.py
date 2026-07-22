"""
mbcommon - shared helpers for MagicBridgeV2 add-on services.

Keeps every sidecar consistent: config loading, branding, logging, and paths
that respect PiKVM's READ-ONLY root filesystem.

Storage model (important on PiKVM OS):
  /etc/magicbridge      -> install-time DEFAULTS only (read-only at runtime)
  /var/lib/magicbridge  -> runtime-mutable state + user config (WRITABLE)

load_config() reads runtime state first, then falls back to the install
default, then to the caller's default. save_config() only ever writes to the
writable state dir, and marks files 0600 (they may hold API keys / creds).
Both dirs are overridable via MB_STATE_DIR / MB_CONFIG_DIR (used by tests).
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
from pathlib import Path

INSTALL_ROOT = Path(os.environ.get("MB_ROOT", "/opt/magicbridge"))
STATE_DIR = Path(os.environ.get("MB_STATE_DIR", "/var/lib/magicbridge"))   # writable
CONFIG_DIR = Path(os.environ.get("MB_CONFIG_DIR", "/etc/magicbridge"))     # read-only defaults


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


_log = get_logger("mbcommon")


def load_branding() -> dict:
    env = {}
    p = INSTALL_ROOT / "branding" / "branding.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class ConfigCorruptError(Exception):
    """A config file EXISTS but could not be parsed.

    Item 38: this must never be quietly downgraded to "empty". Treating a corrupt
    file as empty makes callers bootstrap defaults over it — and for
    `stealth_auth.json` that means `_check_pw` sees no hash and OPENS the stealth
    gate. A truncated file is exactly what a power cut during a write produces, so
    this is a realistic path from "unlucky unplug" to "identity panel unlocked".
    Callers must fail CLOSED; the corrupt file is deliberately left on disk.
    """


def _read_json(path: Path):
    """Return the parsed dict, or None if the file is simply ABSENT.
    Raises ConfigCorruptError if the file exists but does not parse (including a
    zero-length file, the classic interrupted-write result)."""
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as e:                      # unreadable (perms/IO) — do NOT treat as empty
        raise ConfigCorruptError(f"{path}: unreadable: {e}") from e
    try:
        return json.loads(raw)
    except Exception as e:
        raise ConfigCorruptError(f"{path}: invalid JSON ({len(raw)} bytes): {e}") from e


def load_config(name: str, default: dict | None = None) -> dict:
    """Runtime state (writable dir) wins over install default over caller default.

    Fails CLOSED on corruption: if a config file exists but can't be parsed we log
    loudly and raise ConfigCorruptError rather than silently returning defaults
    (item 38). The bad file is left untouched so it can be inspected/recovered —
    nothing bootstraps over it.
    """
    for base in (STATE_DIR, CONFIG_DIR):
        try:
            data = _read_json(base / f"{name}.json")
        except ConfigCorruptError as e:
            _log.error("CORRUPT CONFIG %s.json — refusing to bootstrap defaults over it: %s",
                       name, e)
            raise
        if isinstance(data, dict):
            return data
    return dict(default or {})


def _fs(mode: str):
    """Toggle PiKVM's read-only rootfs. STATE_DIR lives on the root fs (it is NOT a
    tmpfs mount), so a plain write silently fails with EROFS unless we unlock first —
    which is exactly why no MagicBridge setting used to survive a reboot."""
    cmd = "command -v rw >/dev/null && rw || mount -o remount,rw /" if mode == "rw" \
          else "command -v ro >/dev/null && ro || mount -o remount,ro /"
    try:
        subprocess.run(["bash", "-c", cmd], capture_output=True, timeout=15)
    except Exception:
        pass


def save_config(name: str, data: dict) -> bool:
    """Persist to the WRITABLE state dir only (never /etc). Files are 0600.
    Returns True on success; logs and returns False on failure instead of raising,
    so a handler never 500s just because a write failed."""
    _fs("rw")
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(STATE_DIR, 0o700)
        except Exception:
            pass
        target = STATE_DIR / f"{name}.json"
        tmp = STATE_DIR / f".{name}.json.tmp"
        # Item 38: os.replace is atomic, but WITHOUT fsync the file's CONTENTS aren't
        # guaranteed on disk before the rename — a power cut can leave a zero-length or
        # partial file under the real name. fsync the data, then the directory entry,
        # so the rename can only ever expose fully-written bytes.
        with open(tmp, "w") as f:
            f.write(json.dumps(data, indent=2))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, target)   # atomic
        try:
            dfd = os.open(STATE_DIR, os.O_RDONLY)
            try:
                os.fsync(dfd)     # make the rename itself durable
            finally:
                os.close(dfd)
        except Exception:
            pass
        return True
    except Exception as e:
        _log.error("save_config(%s) failed: %s", name, e)
        return False
    finally:
        _fs("ro")


# --- kvmd API base (creds/URL live in kvmd.json; defaults match PiKVM) ---
KVMD_BASE = os.environ.get("MB_KVMD_URL", "https://127.0.0.1/api")
