"""
grafana_embed.py â€” Grafana Panel Embed Config
ankavm v2.5.8 Observability

Features:
  - set_config / get_config (api_key redacted in output)
  - list_dashboards()
  - get_embed_url(dashboard_uid, panel_id, from_, to_) â†’ kiosk iframe src
  - test_connection() â†’ GET grafana /api/health
  - Persisted to /var/lib/ankavm/grafana_config.json
"""

from __future__ import annotations
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

log = logging.getLogger("grafana_embed")

_CONFIG_FILE = Path("/var/lib/ankavm/grafana_config.json")
_lock        = threading.Lock()

_DEFAULT_CONFIG: dict = {
    "grafana_url":  "",
    "api_key":      "",
    "org_id":       1,
    "dashboards":   [],
}


# â”€â”€ Persistence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            cfg = dict(_DEFAULT_CONFIG)
            cfg.update(data)
            return cfg
    except Exception as e:
        log.warning("grafana config load fail: %s", e)
    return dict(_DEFAULT_CONFIG)


def _save(cfg: dict) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_FILE)
    except Exception as e:
        log.warning("grafana config save fail: %s", e)


_config: dict = _load()


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def set_config(
    grafana_url: str,
    api_key: str,
    org_id: int = 1,
    dashboards: Optional[list] = None,
) -> dict:
    """Persist Grafana connection config.  Returns redacted config."""
    global _config
    cfg = {
        "grafana_url": grafana_url.rstrip("/"),
        "api_key":     api_key,
        "org_id":      int(org_id),
        "dashboards":  dashboards if isinstance(dashboards, list) else [],
    }
    with _lock:
        _config = cfg
        _save(cfg)
    return _redact(cfg)


def get_config() -> dict:
    """Return current config with api_key redacted."""
    with _lock:
        return _redact(dict(_config))


def _redact(cfg: dict) -> dict:
    c = dict(cfg)
    if c.get("api_key"):
        c["api_key"] = "***"
    return c


def list_dashboards() -> list:
    """Return configured dashboard list."""
    with _lock:
        return list(_config.get("dashboards", []))


def get_embed_url(
    dashboard_uid: str,
    panel_id: Optional[int] = None,
    from_: str = "now-1h",
    to_:   str = "now",
    theme: str = "dark",
) -> str:
    """
    Build Grafana kiosk iframe src URL.
    Format: <grafana_url>/d/<uid>?orgId=<org>&kiosk&from=...&to=...&panelId=...&theme=...
    """
    with _lock:
        base    = _config.get("grafana_url", "").rstrip("/")
        org_id  = _config.get("org_id", 1)

    if not base:
        return ""

    params = [
        f"orgId={org_id}",
        f"from={from_}",
        f"to={to_}",
        f"theme={theme}",
        "kiosk",
    ]
    if panel_id is not None:
        params.append(f"panelId={int(panel_id)}")
        path = f"/d-solo/{dashboard_uid}"
    else:
        path = f"/d/{dashboard_uid}"

    return f"{base}{path}?{'&'.join(params)}"


def test_connection() -> dict:
    """
    Perform a lightweight GET to Grafana /api/health.
    Returns {ok:bool, status:str, version:str, latency_ms:float}.
    """
    with _lock:
        base    = _config.get("grafana_url", "").rstrip("/")
        api_key = _config.get("api_key", "")

    if not base:
        return {"ok": False, "status": "not_configured", "version": "", "latency_ms": 0}

    url = f"{base}/api/health"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.monotonic()
    try:
        req  = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body    = json.loads(resp.read().decode("utf-8", errors="replace"))
            latency = round((time.monotonic() - t0) * 1000, 1)
            return {
                "ok":         True,
                "status":     body.get("database", "ok"),
                "version":    body.get("version", ""),
                "latency_ms": latency,
            }
    except urllib.error.HTTPError as e:
        latency = round((time.monotonic() - t0) * 1000, 1)
        return {"ok": False, "status": f"http_{e.code}", "version": "", "latency_ms": latency}
    except Exception as e:
        latency = round((time.monotonic() - t0) * 1000, 1)
        return {"ok": False, "status": str(e)[:120], "version": "", "latency_ms": latency}






