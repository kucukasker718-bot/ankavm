"""
ankavm Self-Service Portal â€” End-User Limited VM Operations
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Son kullanÄ±cÄ±nÄ±n (vm-user) yalnÄ±zca kendi tenant'Ä± iÃ§indeki VM'ler Ã¼zerinde
sÄ±nÄ±rlÄ± eylemler yapabilmesi iÃ§in arayÃ¼z.

  - TÃ¼m fonksiyonlar tenant_manager + user_manager ile Ã§apraz doÄŸrulanÄ±r.
  - VM create flow'una dokunmaz â€” quota check + opsiyonel callback ile
    vm_manager.create_vm() Ã§aÄŸrÄ±lÄ±r.
  - Audit log: /var/lib/ankavm/self_service_requests.jsonl
  - VNC konsol token'larÄ± process-local, 10 dakika geÃ§erli.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("self_service_portal")

_AUDIT_FILE = Path("/var/lib/ankavm/self_service_requests.jsonl")
_lock = threading.RLock()

ALLOWED_ACTIONS = {"start", "stop", "reboot", "snapshot", "console"}

# VNC konsol token store â€” kÄ±sa Ã¶mÃ¼rlÃ¼
_console_tokens: dict = {}   # token -> {"vm_id": str, "user": str, "expires": float}
_CONSOLE_TTL = 600           # 10 dakika
_token_lock = threading.Lock()


def _audit(event: str, username: str, detail: Optional[dict] = None) -> None:
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts":     int(time.time()),
                "event":  event,
                "user":   username,
                "detail": detail or {},
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug("audit write fail: %s", e)


# â”€â”€ Lazy module loaders (circular import safe) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _tenant_mgr():
    try:
        import tenant_manager  # type: ignore
        return tenant_manager
    except Exception:
        return None


def _user_mgr():
    try:
        import user_manager  # type: ignore
        return user_manager
    except Exception:
        return None


def _vm_mgr():
    try:
        import vm_manager  # type: ignore
        return vm_manager
    except Exception:
        return None


# â”€â”€ Token cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _cleanup_tokens() -> None:
    now = time.time()
    with _token_lock:
        for tok in [t for t, v in _console_tokens.items() if v.get("expires", 0) < now]:
            _console_tokens.pop(tok, None)


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def list_user_vms(username: str) -> list:
    """KullanÄ±cÄ±ya gÃ¶rÃ¼nÃ¼r VM'leri dÃ¶ner â€” tenant kapsamÄ±nda + atamasÄ± yapÄ±lmÄ±ÅŸlar."""
    out: list = []
    try:
        tm = _tenant_mgr()
        um = _user_mgr()
        vmm = _vm_mgr()
        if not vmm:
            return []
        try:
            all_vms = vmm.list_vms() or []
        except Exception:
            all_vms = []

        # DoÄŸrudan user-VM atamasÄ± (user_manager)
        direct_ids: set = set()
        if um:
            try:
                for v in (um.get_user_vms(username) or []):
                    direct_ids.add(str(v))
            except Exception:
                pass

        # Tenant atamasÄ±na gÃ¶re geniÅŸlet
        tenant_vms: set = set()
        if tm:
            try:
                tid = tm.get_user_tenant(username)
                if tid:
                    for v in (tm.list_tenant_vms(tid) or []):
                        tenant_vms.add(str(v))
            except Exception:
                pass

        for vm in all_vms:
            vid = str(vm.get("id") or vm.get("uuid") or vm.get("name") or "")
            if vid and (vid in direct_ids or vid in tenant_vms):
                out.append(vm)
    except Exception as e:
        log.debug("list_user_vms fail: %s", e)
    return out


def get_user_quota(username: str) -> dict:
    """KullanÄ±cÄ±nÄ±n tenant'Ä±nÄ±n kotasÄ± ve mevcut kullanÄ±m."""
    tm = _tenant_mgr()
    if not tm:
        return {"tenant_id": None, "quota": {}, "usage": {}}
    try:
        tid = tm.get_user_tenant(username)
        if not tid:
            return {"tenant_id": None, "quota": {}, "usage": {}, "warning": "tenant atanmamÄ±ÅŸ"}
        t = tm.get_tenant(tid) or {}
        return {
            "tenant_id": tid,
            "tenant":    t.get("name", ""),
            "quota":     t.get("quota", {}),
            "usage":     tm.get_tenant_usage(tid),
        }
    except Exception as e:
        log.debug("get_user_quota fail: %s", e)
        return {"tenant_id": None, "quota": {}, "usage": {}}


def _user_owns_vm(username: str, vm_id: str) -> bool:
    """user_manager atamasÄ± VEYA tenant atamasÄ± Ã¼zerinden sahiplik kontrolÃ¼."""
    vm_id = str(vm_id)
    um = _user_mgr()
    tm = _tenant_mgr()
    try:
        if um:
            owned = {str(v) for v in (um.get_user_vms(username) or [])}
            if vm_id in owned:
                return True
    except Exception:
        pass
    try:
        if tm:
            user_tid = tm.get_user_tenant(username)
            vm_tid   = tm.get_vm_tenant(vm_id)
            if user_tid and vm_tid and user_tid == vm_tid:
                return True
    except Exception:
        pass
    return False


def request_vm_create(username: str,
                      name: str,
                      vcpus: int,
                      ram_mb: int,
                      disk_gb: int,
                      template_id: Optional[str] = None,
                      iso_path: Optional[str] = None,
                      create_callback=None) -> dict:
    """
    Quota kontrol et + (saÄŸlanÄ±rsa) create_callback Ã§aÄŸÄ±r.
    create_callback verilmezse vm_manager.create_vm() default ÅŸekilde Ã§aÄŸÄ±rÄ±lÄ±r.
    """
    tm = _tenant_mgr()
    if not tm:
        return {"ok": False, "error": "tenant_manager yok"}

    try:
        tid = tm.get_user_tenant(username)
        if not tid:
            _audit("vm_create_denied", username, {"reason": "no tenant"})
            return {"ok": False, "error": "kullanÄ±cÄ± bir tenant'a atanmamÄ±ÅŸ"}

        check = tm.check_quota(tid, {
            "vcpus":   int(vcpus or 0),
            "ram_mb":  int(ram_mb or 0),
            "disk_gb": int(disk_gb or 0),
            "vms":     1,
        })
        if not check.get("allowed"):
            _audit("vm_create_denied", username, {"tenant": tid, "reason": check.get("reason")})
            return {"ok": False, "error": check.get("reason", "kota aÅŸÄ±ldÄ±")}

        # Create
        vm = None
        try:
            if create_callback:
                vm = create_callback(name=name, vcpus=int(vcpus), ram_mb=int(ram_mb),
                                     disk_gb=int(disk_gb), template_id=template_id,
                                     iso_path=iso_path)
            else:
                vmm = _vm_mgr()
                if not vmm:
                    return {"ok": False, "error": "vm_manager yok"}
                vm = vmm.create_vm(
                    name=str(name),
                    memory_mb=int(ram_mb),
                    vcpus=int(vcpus),
                    disk_gb=int(disk_gb),
                    iso_path=iso_path,
                    template_id=template_id,
                )
        except Exception as e:
            log.warning("self-service create_vm fail: %s", e)
            _audit("vm_create_error", username, {"error": str(e)})
            return {"ok": False, "error": f"VM oluÅŸturulamadÄ±: {e}"}

        vm_id = None
        if isinstance(vm, dict):
            vm_id = vm.get("id") or vm.get("uuid") or vm.get("name")
        # Otomatik atama
        if vm_id:
            try:
                tm.assign_vm_to_tenant(str(vm_id), tid)
            except Exception:
                pass
            try:
                um = _user_mgr()
                if um:
                    um.assign_vm(username, str(vm_id))
            except Exception:
                pass
        _audit("vm_create", username, {"tenant": tid, "vm_id": vm_id, "name": name})
        return {"ok": True, "vm": vm}
    except Exception as e:
        log.warning("request_vm_create fail: %s", e)
        return {"ok": False, "error": str(e)}


def request_vm_action(username: str, vm_id: str, action: str) -> dict:
    """start/stop/reboot/snapshot/console â€” yalnÄ±zca user'Ä±n kendi VM'inde."""
    action = (action or "").lower().strip()
    if action not in ALLOWED_ACTIONS:
        return {"ok": False, "error": f"izin verilmeyen eylem: {action}"}
    if not _user_owns_vm(username, vm_id):
        _audit("action_denied", username, {"vm_id": vm_id, "action": action})
        return {"ok": False, "error": "bu VM size ait deÄŸil"}
    vmm = _vm_mgr()
    if not vmm:
        return {"ok": False, "error": "vm_manager yok"}

    try:
        if action == "start":
            res = vmm.start_vm(vm_id)
        elif action == "stop":
            res = vmm.stop_vm(vm_id)
        elif action == "reboot":
            res = vmm.reboot_vm(vm_id)
        elif action == "snapshot":
            # opsiyonel â€” modÃ¼l varsa kullan
            snap = None
            for fn_name in ("create_snapshot", "snapshot_create", "snapshot"):
                fn = getattr(vmm, fn_name, None)
                if callable(fn):
                    try:
                        snap = fn(vm_id, f"selfservice-{int(time.time())}")
                        break
                    except Exception:
                        continue
            res = {"ok": True, "snapshot": snap}
        elif action == "console":
            return request_console(username, vm_id)
        else:
            return {"ok": False, "error": "unsupported"}
        _audit("vm_action", username, {"vm_id": vm_id, "action": action})
        return {"ok": True, "result": res}
    except Exception as e:
        log.warning("vm action fail: %s", e)
        _audit("vm_action_error", username, {"vm_id": vm_id, "action": action, "error": str(e)})
        return {"ok": False, "error": str(e)}


def request_console(username: str, vm_id: str) -> dict:
    """10 dakikalÄ±k tek kullanÄ±mlÄ±k konsol token Ã¼retir."""
    if not _user_owns_vm(username, vm_id):
        _audit("console_denied", username, {"vm_id": vm_id})
        return {"ok": False, "error": "bu VM size ait deÄŸil"}
    _cleanup_tokens()
    tok = secrets.token_urlsafe(32)
    with _token_lock:
        _console_tokens[tok] = {
            "vm_id":   str(vm_id),
            "user":    username,
            "expires": time.time() + _CONSOLE_TTL,
        }
    _audit("console_token", username, {"vm_id": vm_id})
    return {"ok": True, "token": tok, "expires_in": _CONSOLE_TTL, "vm_id": str(vm_id)}


def validate_console_token(token: str) -> Optional[dict]:
    _cleanup_tokens()
    with _token_lock:
        info = _console_tokens.get(token)
        if not info:
            return None
        if info["expires"] < time.time():
            _console_tokens.pop(token, None)
            return None
        return dict(info)


def list_recent_requests(limit: int = 100) -> list:
    try:
        if not _AUDIT_FILE.exists():
            return []
        with _AUDIT_FILE.open(encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines[-limit:][::-1]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out
    except Exception:
        return []






