"""
ankavm App-Consistent Snapshot — v2.5.7
────────────────────────────────────────
guest-agent fsfreeze ile DB-tutarlı (quiesced) snapshot yönetimi.

API:
    create_consistent_snapshot(vm_id, name, freeze_fs=True) -> dict
    list_consistent_snapshots(vm_id) -> list
    get_quiesce_support(vm_id) -> dict  {agent: bool, fsfreeze: bool}
    register_app_hook(vm_id, app, pre_cmd, post_cmd) -> dict
    list_app_hooks(vm_id) -> list

Persistent state: /var/lib/ankavm/consistent_snapshots.json
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("app_consistent_snapshot")

_DATA_FILE  = Path("/var/lib/ankavm/consistent_snapshots.json")
_HOOKS_FILE = Path("/var/lib/ankavm/app_snapshot_hooks.json")
_lock       = threading.Lock()

# libvirt optional
try:
    import libvirt as _libvirt
    _LIBVIRT_OK = True
except ImportError:
    _libvirt = None
    _LIBVIRT_OK = False


# ── I/O helpers ──────────────────────────────────────────────────────────────

def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("load fail %s: %s", path, e)
    return {}


def _save(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.warning("save fail %s: %s", path, e)


# ── libvirt helpers ───────────────────────────────────────────────────────────

def _get_domain(conn, vm_id: str):
    try:
        return conn.lookupByName(vm_id)
    except Exception:
        try:
            return conn.lookupByUUIDString(vm_id)
        except Exception:
            return None


def _agent_available(domain) -> bool:
    """QEMU guest agent ping."""
    try:
        result = domain.qemuAgentCommand(
            '{"execute":"guest-ping"}', 3, 0
        )
        return bool(result)
    except Exception:
        return False


def _fsfreeze(domain) -> bool:
    try:
        domain.fsFreeze(None, 0)
        return True
    except Exception as e:
        log.warning("fsfreeze fail: %s", e)
        return False


def _fsthaw(domain) -> bool:
    try:
        domain.fsThaw(None, 0)
        return True
    except Exception as e:
        log.warning("fsthaw fail: %s", e)
        return False


# ── App hooks ─────────────────────────────────────────────────────────────────

def _run_hook_cmd(domain, cmd: str) -> bool:
    """Run a command inside the guest via QEMU agent (exec)."""
    if not cmd:
        return True
    try:
        exec_payload = json.dumps({
            "execute": "guest-exec",
            "arguments": {
                "path": "/bin/sh",
                "arg": ["-c", cmd],
                "capture-output": True,
            }
        })
        resp_raw = domain.qemuAgentCommand(exec_payload, 10, 0)
        resp = json.loads(resp_raw)
        pid = resp.get("return", {}).get("pid")
        if pid is None:
            return False
        # wait for completion
        for _ in range(30):
            time.sleep(0.5)
            status_raw = domain.qemuAgentCommand(
                json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}}),
                5, 0
            )
            status = json.loads(status_raw).get("return", {})
            if status.get("exited"):
                return status.get("exitcode", 1) == 0
        return False
    except Exception as e:
        log.warning("hook cmd fail '%s': %s", cmd, e)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def create_consistent_snapshot(vm_id: str, name: str, freeze_fs: bool = True) -> dict:
    """
    guest-agent fsfreeze → libvirt snapshot → fsthaw.
    Agent yoksa normal snapshot alınır + uyarı eklenir.
    """
    if not _LIBVIRT_OK:
        return {"ok": False, "error": "libvirt kurulu değil"}

    ts = int(time.time())
    snap_id = str(uuid.uuid4())[:8]
    warnings = []

    try:
        conn = _libvirt.open("qemu:///system")
    except Exception as e:
        return {"ok": False, "error": f"libvirt bağlantı hatası: {e}"}

    try:
        domain = _get_domain(conn, vm_id)
        if domain is None:
            return {"ok": False, "error": f"VM bulunamadı: {vm_id}"}

        agent_ok = _agent_available(domain)
        frozen   = False

        # Run app pre-hooks first
        hooks = list_app_hooks(vm_id)
        for h in hooks:
            if h.get("pre_cmd"):
                if agent_ok:
                    _run_hook_cmd(domain, h["pre_cmd"])
                else:
                    warnings.append(f"pre-hook atlandı (agent yok): {h['app']}")

        # fsfreeze
        if freeze_fs:
            if agent_ok:
                frozen = _fsfreeze(domain)
                if not frozen:
                    warnings.append("fsfreeze başarısız — normal snapshot alınıyor")
            else:
                warnings.append("guest-agent bulunamadı — quiesced olmayan snapshot")

        # libvirt snapshot XML
        xml = (
            f'<domainsnapshot>'
            f'<name>{name}-{snap_id}</name>'
            f'<description>ankavm app-consistent {ts}</description>'
            f'</domainsnapshot>'
        )
        try:
            snap = domain.snapshotCreateXML(xml, 0)
            snap_name = snap.getName()
        except Exception as e:
            # thaw before returning
            if frozen:
                _fsthaw(domain)
            return {"ok": False, "error": f"snapshot oluşturulamadı: {e}"}
        finally:
            if frozen:
                _fsthaw(domain)

        # Run app post-hooks
        for h in hooks:
            if h.get("post_cmd"):
                if agent_ok:
                    _run_hook_cmd(domain, h["post_cmd"])
                else:
                    warnings.append(f"post-hook atlandı (agent yok): {h['app']}")

        # Persist record
        with _lock:
            data = _load(_DATA_FILE)
            data.setdefault(vm_id, []).append({
                "id":          snap_id,
                "name":        snap_name,
                "label":       name,
                "ts":          ts,
                "quiesced":    frozen,
                "agent_used":  agent_ok,
                "warnings":    warnings,
            })
            _save(_DATA_FILE, data)

        conn.close()
        return {
            "ok":        True,
            "snap_id":   snap_id,
            "snap_name": snap_name,
            "quiesced":  frozen,
            "agent":     agent_ok,
            "warnings":  warnings,
        }

    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        log.error("create_consistent_snapshot fail vm=%s: %s", vm_id, e)
        return {"ok": False, "error": str(e)}


def list_consistent_snapshots(vm_id: str) -> list:
    with _lock:
        data = _load(_DATA_FILE)
    return data.get(vm_id, [])


def get_quiesce_support(vm_id: str) -> dict:
    """Probe agent + fsfreeze capability."""
    result = {"agent": False, "fsfreeze": False, "vm_id": vm_id}
    if not _LIBVIRT_OK:
        result["error"] = "libvirt kurulu değil"
        return result
    try:
        conn = _libvirt.open("qemu:///system")
        domain = _get_domain(conn, vm_id)
        if domain is None:
            result["error"] = f"VM bulunamadı: {vm_id}"
            conn.close()
            return result
        agent_ok = _agent_available(domain)
        result["agent"] = agent_ok
        if agent_ok:
            # Try to detect fsfreeze support via guest-exec
            try:
                exec_payload = json.dumps({
                    "execute": "guest-exec",
                    "arguments": {
                        "path": "/bin/sh",
                        "arg": ["-c", "which fsfreeze || true"],
                        "capture-output": True,
                    }
                })
                resp = json.loads(domain.qemuAgentCommand(exec_payload, 5, 0))
                result["fsfreeze"] = bool(resp.get("return", {}).get("pid"))
            except Exception:
                result["fsfreeze"] = False
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


# ── App Hooks (MySQL FLUSH TABLES, etc.) ─────────────────────────────────────

def register_app_hook(vm_id: str, app: str, pre_cmd: str, post_cmd: str) -> dict:
    """
    Register a pre/post snapshot hook for an application inside the VM.
    Example: app='mysql', pre_cmd='mysql -e "FLUSH TABLES WITH READ LOCK"'
    """
    if not app or not app.strip():
        return {"ok": False, "error": "app adı zorunlu"}
    with _lock:
        data = _load(_HOOKS_FILE)
        hooks = data.setdefault(vm_id, [])
        # Update existing or append
        for h in hooks:
            if h.get("app") == app.strip():
                h["pre_cmd"]  = pre_cmd or ""
                h["post_cmd"] = post_cmd or ""
                h["updated"]  = int(time.time())
                _save(_HOOKS_FILE, data)
                return {"ok": True, "action": "updated", "app": app}
        hooks.append({
            "app":      app.strip(),
            "pre_cmd":  pre_cmd  or "",
            "post_cmd": post_cmd or "",
            "created":  int(time.time()),
        })
        _save(_HOOKS_FILE, data)
    return {"ok": True, "action": "created", "app": app}


def list_app_hooks(vm_id: str) -> list:
    with _lock:
        data = _load(_HOOKS_FILE)
    return data.get(vm_id, [])






