"""
edge_mode.py â€” Edge Deployment Manager for ankavm
ankavm v2.5.11 Modern Workloads

Features:
  - get_edge_status() â€” edge mode enabled, central URL, last heartbeat
  - configure_edge(central_url, node_id, heartbeat_interval, low_resource) â€” save config
  - send_heartbeat() â€” single manual heartbeat to central management URL
  - get_resource_profile() â€” trimmed resource profile for edge (which services scaled back)
  - apply_low_resource_mode(enabled) â€” set low_resource flag (config, no auto-loops)

Config persisted to /var/lib/ankavm/edge_config.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

log = logging.getLogger("edge_mode")

_CONFIG_FILE = Path("/var/lib/ankavm/edge_config.json")
_lock = threading.Lock()

_DEFAULT_CONFIG = {
    "enabled":             False,
    "central_url":         None,
    "node_id":             None,
    "heartbeat_interval":  60,
    "low_resource":        False,
    "last_heartbeat":      None,
    "last_heartbeat_ok":   None,
    "last_heartbeat_err":  None,
}

# Services considered "heavy" â€” these get a note in low-resource profile
_HEAVY_SERVICES = [
    "otel_tracing",
    "grafana_embed",
    "topology_viz",
    "anomaly_detector",
    "session_recorder",
    "vnc_thumbnail",
]


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            # Merge with defaults for any missing keys
            cfg = dict(_DEFAULT_CONFIG)
            cfg.update(data)
            return cfg
    except Exception as e:
        log.warning("edge_mode load fail: %s", e)
    return dict(_DEFAULT_CONFIG)


def _save(data: dict) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_FILE)
    except Exception as e:
        log.warning("edge_mode save fail: %s", e)


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_edge_status() -> dict:
    """Return current edge mode status."""
    with _lock:
        cfg = _load()
    return {
        "enabled":            cfg["enabled"],
        "central_url":        cfg["central_url"],
        "node_id":            cfg["node_id"],
        "heartbeat_interval": cfg["heartbeat_interval"],
        "low_resource":       cfg["low_resource"],
        "last_heartbeat":     cfg["last_heartbeat"],
        "last_heartbeat_ok":  cfg["last_heartbeat_ok"],
        "last_heartbeat_err": cfg["last_heartbeat_err"],
    }


def configure_edge(
    central_url: Optional[str] = None,
    node_id: Optional[str] = None,
    heartbeat_interval: int = 60,
    low_resource: bool = False,
) -> dict:
    """Save edge deployment configuration."""
    with _lock:
        cfg = _load()
        if central_url is not None:
            cfg["central_url"] = str(central_url).strip() or None
        if node_id is not None:
            cfg["node_id"] = str(node_id).strip() or None
        cfg["heartbeat_interval"] = max(10, int(heartbeat_interval))
        cfg["low_resource"] = bool(low_resource)
        cfg["enabled"] = bool(cfg["central_url"])
        _save(cfg)
    return {"configured": True, "config": {k: cfg[k] for k in (
        "enabled", "central_url", "node_id", "heartbeat_interval", "low_resource"
    )}}


def send_heartbeat() -> dict:
    """
    Send a single heartbeat POST to the central management URL.
    This is a manual/cron operation â€” no auto-loop.
    Returns {sent, response, error}.
    """
    with _lock:
        cfg = _load()
    central_url = cfg.get("central_url")
    node_id     = cfg.get("node_id") or _get_local_node_id()
    if not central_url:
        return {"sent": False, "error": "central_url not configured"}

    payload = json.dumps({
        "node_id":      node_id,
        "timestamp":    int(time.time()),
        "low_resource": cfg.get("low_resource", False),
        "version":      "2.5.11",
    }).encode("utf-8")

    url = central_url.rstrip("/") + "/api/edge/heartbeat"
    result: dict = {"sent": False, "response": None, "error": None, "url": url}
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "X-ankavm-Node": node_id},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            result["sent"]     = True
            result["response"] = body[:1024]
            result["status"]   = resp.status
    except urllib.error.URLError as e:
        result["error"] = str(e.reason)
        log.debug("heartbeat fail: %s", e)
    except Exception as e:
        result["error"] = str(e)
        log.debug("heartbeat fail: %s", e)

    # Persist result
    with _lock:
        cfg = _load()
        cfg["last_heartbeat"]    = int(time.time())
        cfg["last_heartbeat_ok"] = result["sent"]
        cfg["last_heartbeat_err"] = result.get("error")
        _save(cfg)

    return result


def get_resource_profile() -> dict:
    """
    Return a resource profile tailored for edge deployment.
    Lists heavy services that are recommended to be disabled in low-resource mode.
    """
    with _lock:
        cfg = _load()
    low = cfg.get("low_resource", False)
    # Basic host metrics via /proc (no external deps)
    mem_total_mb = _read_proc_meminfo("MemTotal")
    mem_avail_mb = _read_proc_meminfo("MemAvailable")
    cpu_count = os.cpu_count() or 1
    return {
        "low_resource_mode": low,
        "recommended_disabled": _HEAVY_SERVICES if low else [],
        "host_cpu_count":    cpu_count,
        "host_mem_total_mb": mem_total_mb,
        "host_mem_avail_mb": mem_avail_mb,
        "edge_tier":         "constrained" if (mem_total_mb or 0) < 2048 else "standard",
    }


def apply_low_resource_mode(enabled: bool) -> dict:
    """
    Set the low_resource config flag.
    This is a configuration flag only â€” actual service management is
    handled by each service module (no force-kills here).
    """
    with _lock:
        cfg = _load()
        cfg["low_resource"] = bool(enabled)
        _save(cfg)
    return {
        "low_resource": bool(enabled),
        "note": "flag saved; restart affected services to apply changes",
        "affected_services": _HEAVY_SERVICES if enabled else [],
    }


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_local_node_id() -> str:
    """Derive a stable node ID from hostname + machine-id."""
    try:
        hostname = subprocess.run(
            ["hostname", "-f"], capture_output=True, text=True, timeout=3
        ).stdout.strip()
    except Exception:
        hostname = "unknown"
    machine_id = ""
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            machine_id = Path(p).read_text().strip()[:8]
            break
        except Exception:
            pass
    return f"{hostname}-{machine_id}" if machine_id else hostname


def _read_proc_meminfo(key: str) -> Optional[int]:
    """Read a value from /proc/meminfo, return kBâ†’MB integer or None."""
    try:
        content = Path("/proc/meminfo").read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith(key + ":"):
                kb = int(line.split()[1])
                return kb // 1024
    except Exception:
        pass
    return None






