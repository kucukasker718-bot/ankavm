"""
ankavm Electron/Desktop Client â€” API tokens + manifest
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Generates long-lived API tokens for registered desktop clients
(Electron, CLI, etc.), stores client registry, and provides
connection config + download links (placeholder release URLs).
No external deps beyond stdlib.
"""

import json
import time
import uuid
import hmac
import hashlib
import secrets
import logging
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("electron_client")

_CLIENTS_FILE = Path("/var/lib/ankavm/desktop_clients.json")
_lock         = threading.Lock()

# Token lifetime: 365 days (long-lived for desktop clients)
_TOKEN_TTL_SECS = 365 * 24 * 3600

# Download base URL â€” points to GitHub releases / gh-pages
_DOWNLOAD_BASE = "https://shinnasukha.github.io/ankavm/releases"
_RELEASES = {
    "latest": "v0.1.0",
    "assets": [
        {
            "platform": "linux",
            "arch":     "x64",
            "format":   "AppImage",
            "url":      f"{_DOWNLOAD_BASE}/ankavm-desktop-0.1.0-linux-x64.AppImage",
            "sha256":   None,
        },
        {
            "platform": "windows",
            "arch":     "x64",
            "format":   "exe",
            "url":      f"{_DOWNLOAD_BASE}/ankavm-desktop-0.1.0-win-x64.exe",
            "sha256":   None,
        },
        {
            "platform": "macos",
            "arch":     "arm64",
            "format":   "dmg",
            "url":      f"{_DOWNLOAD_BASE}/ankavm-desktop-0.1.0-macos-arm64.dmg",
            "sha256":   None,
        },
        {
            "platform": "macos",
            "arch":     "x64",
            "format":   "dmg",
            "url":      f"{_DOWNLOAD_BASE}/ankavm-desktop-0.1.0-macos-x64.dmg",
            "sha256":   None,
        },
    ],
}


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_clients() -> dict:
    try:
        if _CLIENTS_FILE.exists():
            return json.loads(_CLIENTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("desktop clients load fail: %s", e)
    return {}


def _save_clients(data: dict) -> None:
    try:
        _CLIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CLIENTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CLIENTS_FILE)
    except Exception as e:
        log.warning("desktop clients save fail: %s", e)


def _generate_token(client_id: str) -> str:
    """Generate a long-lived opaque API token."""
    rand  = secrets.token_hex(32)
    stamp = str(int(time.time()))
    raw   = f"ankavm-desktop:{client_id}:{stamp}:{rand}"
    return "oxdt_" + hashlib.sha256(raw.encode()).hexdigest()


# â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_client_config(server_url: str) -> dict:
    """
    Return a JSON config blob for an Electron client to bootstrap
    its connection to this ankavm server.
    """
    if not server_url:
        raise ValueError("server_url required")
    return {
        "ankavm_api": server_url.rstrip("/"),
        "api_version": "v1",
        "specversion": "2.5.12",
        "auth_endpoint": "/api/login",
        "ws_endpoint":   "/socket.io",
        "tls_required":  server_url.startswith("https://"),
        "generated_at":  int(time.time()),
    }


def register_client(name: str, platform: str,
                    description: str = "") -> dict:
    """
    Register a new desktop client and issue a long-lived API token.
    platform: 'linux' | 'windows' | 'macos' | 'other'
    """
    if not name:
        raise ValueError("name required")
    valid_platforms = {"linux", "windows", "macos", "other"}
    if platform not in valid_platforms:
        platform = "other"

    client_id = uuid.uuid4().hex[:14]
    token     = _generate_token(client_id)
    client = {
        "id":          client_id,
        "name":        name,
        "platform":    platform,
        "description": description,
        "token":       token,
        "token_prefix": token[:12] + "...",  # for display only
        "created_at":  int(time.time()),
        "expires_at":  int(time.time()) + _TOKEN_TTL_SECS,
        "last_seen":   None,
        "revoked":     False,
    }
    with _lock:
        clients = _load_clients()
        clients[client_id] = client
        _save_clients(clients)
    log.info("desktop client registered: %s (%s, %s)", client_id, name, platform)
    # Return full token once â€” caller must store it
    return client


def list_clients() -> list:
    with _lock:
        clients = _load_clients()
    out = []
    for c in clients.values():
        row = dict(c)
        row.pop("token", None)  # never expose full token in list
        out.append(row)
    return sorted(out, key=lambda x: x.get("created_at", 0), reverse=True)


def revoke_client(client_id: str) -> dict:
    with _lock:
        clients = _load_clients()
        if client_id not in clients:
            return {"ok": False, "error": "not found"}
        clients[client_id]["revoked"]    = True
        clients[client_id]["revoked_at"] = int(time.time())
        _save_clients(clients)
    log.info("desktop client revoked: %s", client_id)
    return {"ok": True, "revoked": client_id}


def get_download_links() -> dict:
    """Return Electron client download links (placeholder release URLs)."""
    return _RELEASES


def validate_token(token: str) -> Optional[dict]:
    """
    Check if token is valid (non-revoked, non-expired).
    Returns client dict or None.
    """
    if not token or not token.startswith("oxdt_"):
        return None
    with _lock:
        clients = _load_clients()
    now = int(time.time())
    for c in clients.values():
        if c.get("token") == token:
            if c.get("revoked"):
                return None
            if c.get("expires_at", 0) < now:
                return None
            return c
    return None






