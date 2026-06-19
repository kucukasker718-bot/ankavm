"""
ankavm Per-Tenant API Rate Limiting (Token Bucket)
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
In-memory token-bucket â€” process-local.  Persistent deÄŸil; sadece varsayÄ±lan
config persist edilir.  Yeniden baÅŸlatmada bucket'lar full doluya reset olur
(operatÃ¶r iÃ§in kabul edilebilir trade-off).

  - Default: 100 rpm, 200 burst per tenant
  - Thread-safe (threading.Lock)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

log = logging.getLogger("tenant_rate_limit")

_CFG_FILE = Path("/var/lib/ankavm/tenant_rate_limit.json")
_lock     = threading.Lock()

DEFAULT_RPM   = 100
DEFAULT_BURST = 200

# tenant_id -> {"rpm": int, "burst": int}
_limits: dict = {}

# tenant_id -> {"tokens": float, "last": float, "history": deque[ts]}
_state: dict = {}


# â”€â”€ Persistence (yalnÄ±zca config defaults) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _load_cfg() -> None:
    global _limits
    try:
        if _CFG_FILE.exists():
            data = json.loads(_CFG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _limits = {
                    str(k): {
                        "rpm":   int(v.get("rpm", DEFAULT_RPM)),
                        "burst": int(v.get("burst", DEFAULT_BURST)),
                    }
                    for k, v in data.items()
                    if isinstance(v, dict)
                }
    except Exception as e:
        log.warning("rate-limit cfg load fail: %s", e)


def _save_cfg() -> None:
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CFG_FILE.write_text(json.dumps(_limits, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("rate-limit cfg save fail: %s", e)


# Initial load (best-effort)
try:
    _load_cfg()
except Exception:
    pass


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_limit(tenant_id: str) -> dict:
    with _lock:
        cfg = _limits.get(tenant_id) or {"rpm": DEFAULT_RPM, "burst": DEFAULT_BURST}
        return dict(cfg)


def set_limit(tenant_id: str, rpm: int = DEFAULT_RPM, burst: int = DEFAULT_BURST) -> dict:
    try:
        rpm   = max(1, int(rpm))
        burst = max(1, int(burst))
    except Exception:
        return {"ok": False, "error": "rpm/burst geÃ§ersiz"}
    with _lock:
        _limits[str(tenant_id)] = {"rpm": rpm, "burst": burst}
        _save_cfg()
        # State'i sÄ±fÄ±rla â€” yeni burst deÄŸeri ile baÅŸlasÄ±n
        _state[str(tenant_id)] = {
            "tokens":  float(burst),
            "last":    time.time(),
            "history": deque(),
        }
    return {"ok": True, "tenant_id": tenant_id, "rpm": rpm, "burst": burst}


def _bucket(tenant_id: str) -> tuple:
    """Lock altÄ±nda Ã§aÄŸrÄ±lmalÄ±."""
    cfg = _limits.get(tenant_id) or {"rpm": DEFAULT_RPM, "burst": DEFAULT_BURST}
    st  = _state.get(tenant_id)
    if not st:
        st = {
            "tokens":  float(cfg["burst"]),
            "last":    time.time(),
            "history": deque(),
        }
        _state[tenant_id] = st
    return cfg, st


def _refill(cfg: dict, st: dict) -> None:
    now = time.time()
    elapsed = max(0.0, now - st["last"])
    refill = elapsed * (cfg["rpm"] / 60.0)
    st["tokens"] = min(float(cfg["burst"]), st["tokens"] + refill)
    st["last"]   = now


def _trim_history(st: dict, now: float) -> None:
    cutoff = now - 3600.0
    h = st["history"]
    while h and h[0] < cutoff:
        h.popleft()


def check_rate_limit(tenant_id: str, endpoint: str = "") -> dict:
    """1 token tÃ¼ketir. allowed=True ise geÃ§ti, False ise retry_after_sec dÃ¶ner."""
    if not tenant_id:
        # KimliÄŸi yok ise rate-limit'i atla â€” admin/auth katmanÄ± zaten reddeder
        return {"allowed": True, "retry_after_sec": 0}
    tenant_id = str(tenant_id)
    now = time.time()
    with _lock:
        cfg, st = _bucket(tenant_id)
        _refill(cfg, st)
        if st["tokens"] >= 1.0:
            st["tokens"] -= 1.0
            st["history"].append(now)
            _trim_history(st, now)
            return {"allowed": True, "retry_after_sec": 0}
        # Eksik token kadar bekleme sÃ¼resi
        deficit = 1.0 - st["tokens"]
        retry   = max(1, int(deficit * 60.0 / cfg["rpm"]) + 1)
        log.debug("rate-limit deny tenant=%s endpoint=%s retry=%ds",
                  tenant_id, endpoint, retry)
        return {"allowed": False, "retry_after_sec": retry}


def get_usage(tenant_id: str) -> dict:
    tenant_id = str(tenant_id)
    now = time.time()
    with _lock:
        cfg, st = _bucket(tenant_id)
        _refill(cfg, st)
        _trim_history(st, now)
        return {
            "tenant_id":                tenant_id,
            "rpm":                      cfg["rpm"],
            "burst":                    cfg["burst"],
            "current_tokens":           round(st["tokens"], 2),
            "last_refill_ts":           int(st["last"]),
            "total_requests_last_hour": len(st["history"]),
        }


def reset(tenant_id: Optional[str] = None) -> dict:
    with _lock:
        if tenant_id:
            _state.pop(str(tenant_id), None)
        else:
            _state.clear()
    return {"ok": True}


def list_limits() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _limits.items()}






