"""SEC-032 — Persistent SSH known-hosts file with first-contact prompt.

ankavm used `paramiko.AutoAddPolicy()` for every outbound SSH connection,
which transparently trusts whatever key the peer presents. This module
replaces that pattern with a persistent known-hosts file at
`/var/lib/ankavm/known_hosts` plus a pending-prompts queue that the
panel surfaces so the operator can approve a new host fingerprint once.

Usage from the rest of the backend:

    from ssh_known_hosts import ankavmPolicy, load_known_hosts

    client.load_host_keys(load_known_hosts())
    client.set_missing_host_key_policy(ankavmPolicy())

Pending approvals are listed via `pending_prompts()` and resolved with
`approve(host_key_record_id)` or `reject(host_key_record_id)`.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

try:
    import paramiko  # type: ignore
except Exception:  # paramiko optional in test envs
    paramiko = None  # type: ignore

log = logging.getLogger("ankavm.ssh_known_hosts")

_KNOWN_HOSTS_PATH = Path("/var/lib/ankavm/known_hosts")
_PENDING_PATH = Path("/var/lib/ankavm/known_hosts_pending.json")
_LOCK = threading.Lock()


def _ensure() -> None:
    try:
        _KNOWN_HOSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _KNOWN_HOSTS_PATH.exists():
            _KNOWN_HOSTS_PATH.touch(mode=0o600)
    except Exception as e:
        log.debug("ensure failed: %s", e)


def load_known_hosts():
    """Return a paramiko HostKeys object pre-loaded from disk."""
    _ensure()
    if paramiko is None:
        return None
    hk = paramiko.hostkeys.HostKeys()
    try:
        hk.load(str(_KNOWN_HOSTS_PATH))
    except Exception as e:
        log.warning("known_hosts load failed: %s", e)
    return hk


def fingerprint(key) -> str:
    """Return a base64-encoded SHA256 fingerprint of a paramiko PKey."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode()


def _load_pending() -> list:
    if not _PENDING_PATH.exists():
        return []
    try:
        return json.loads(_PENDING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_pending(items: list) -> None:
    _ensure()
    tmp = _PENDING_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, _PENDING_PATH)


def pending_prompts() -> list:
    """List host-key approvals the operator has not yet acted on."""
    with _LOCK:
        return _load_pending()


def approve(prompt_id: str) -> dict:
    """Approve a pending first-contact prompt and persist the key to
    known_hosts. The next connection to this host will succeed silently."""
    with _LOCK:
        items = _load_pending()
        for i, p in enumerate(items):
            if p.get("id") == prompt_id:
                _append_known_host(p["hostname"], p["key_type"], p["key_b64"])
                items.pop(i)
                _save_pending(items)
                return {"ok": True, "approved": prompt_id}
        return {"ok": False, "error": "not found"}


def reject(prompt_id: str) -> dict:
    with _LOCK:
        items = _load_pending()
        new = [p for p in items if p.get("id") != prompt_id]
        if len(new) == len(items):
            return {"ok": False, "error": "not found"}
        _save_pending(new)
        return {"ok": True, "rejected": prompt_id}


def _append_known_host(hostname: str, key_type: str, key_b64: str) -> None:
    _ensure()
    line = f"{hostname} {key_type} {key_b64}\n"
    with open(_KNOWN_HOSTS_PATH, "a", encoding="utf-8") as f:
        f.write(line)


class ankavmPolicy:
    """A paramiko MissingHostKeyPolicy that:
      * trusts hosts already in known_hosts (handled by paramiko before us)
      * queues a first-contact prompt for unknown hosts and refuses the
        connection until the operator approves it via the panel
      * trust-on-first-use is opt-in via ankavm_SSH_TOFU=1 for migration
    """

    def missing_host_key(self, client, hostname, key):
        fp = fingerprint(key)
        key_type = key.get_name()
        key_b64 = base64.b64encode(key.asbytes()).decode()
        prompt = {
            "id": hashlib.sha256(
                f"{hostname}|{key_type}|{key_b64}".encode()
            ).hexdigest()[:16],
            "hostname": hostname,
            "key_type": key_type,
            "key_b64": key_b64,
            "fingerprint": fp,
            "first_seen": time.time(),
        }
        with _LOCK:
            items = _load_pending()
            if not any(p["id"] == prompt["id"] for p in items):
                items.append(prompt)
                _save_pending(items)
        log.warning("ssh_known_hosts: queued first-contact prompt for "
                    "%s (%s)", hostname, fp)
        if os.environ.get("ankavm_SSH_TOFU") == "1":
            _append_known_host(hostname, key_type, key_b64)
            return
        raise Exception(
            f"unknown ssh host {hostname!r} (fingerprint {fp}); "
            f"approve via panel → Security → SSH Known Hosts"
        )






