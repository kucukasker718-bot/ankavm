"""ankavm PWA offline support (v3.0).

Generates a service-worker manifest + cache list so the panel keeps a
read-only fallback view available when the network is down. The
service worker fetches the listed static assets at install time, and
the panel falls back to the latest cached `/api/vms`, `/api/hosts`,
and `/api/networks` responses when fetch fails.

This module returns the manifest data; the actual service worker is
served from `/sw.js` (already exists in `ankavm/frontend/static/sw.js`).
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ankavm.pwa")
_CONFIG_PATH = Path("/var/lib/ankavm/pwa_offline.json")

DEFAULT_CACHE = [
    "/",
    "/static/manifest.json",
    "/static/img/ankavm-icon.png",
    "/static/xterm.min.css",
    "/static/xterm.min.js",
    "/static/chart.umd.min.js",
]

DEFAULT_API_FALLBACKS = [
    "/api/vms",
    "/api/hosts",
    "/api/networks",
    "/api/storage/pools",
    "/api/monitoring/global",
]


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {
            "enabled": True,
            "cache_version": _bump_version(""),
            "cache": list(DEFAULT_CACHE),
            "api_fallbacks": list(DEFAULT_API_FALLBACKS),
            "max_api_cache_age_sec": 600,
        }
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False, "cache": [], "api_fallbacks": []}


def _save_config(d: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, _CONFIG_PATH)


def _bump_version(seed: str) -> str:
    h = hashlib.sha256((seed + str(time.time())).encode()).hexdigest()
    return f"ankavm-v{h[:8]}"


def status() -> dict:
    return _load_config()


def bump_cache_version() -> dict:
    cfg = _load_config()
    cfg["cache_version"] = _bump_version(cfg.get("cache_version", ""))
    _save_config(cfg)
    log.info("PWA cache version bumped: %s", cfg["cache_version"])
    return {"ok": True, "cache_version": cfg["cache_version"]}


def set_enabled(enabled: bool) -> dict:
    cfg = _load_config()
    cfg["enabled"] = bool(enabled)
    _save_config(cfg)
    return {"ok": True, "enabled": cfg["enabled"]}


def sw_manifest() -> dict:
    """Return the manifest the service worker fetches from /api/pwa/manifest
    so it can populate its install-time cache."""
    cfg = _load_config()
    return {
        "version": cfg.get("cache_version", "ankavm-v0"),
        "precache": cfg.get("cache", DEFAULT_CACHE),
        "api_fallbacks": cfg.get("api_fallbacks", DEFAULT_API_FALLBACKS),
        "max_api_cache_age_sec": cfg.get("max_api_cache_age_sec", 600),
        "enabled": cfg.get("enabled", True),
    }






