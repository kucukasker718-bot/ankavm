"""
ankavm Tenant Manager — Hard Multi-Tenancy Isolation
─────────────────────────────────────────────────────
Tenants, kotalar, user→tenant ve vm→tenant atamaları.

  - Persistent state: /var/lib/ankavm/tenants.json (atomic write)
  - Thread-safe (RLock)
  - Network namespace: yalnızca config kaydı — `ip netns add` çağırmaz
    (production'da host'a yük yapar, ayrı bir job ile uygulanmalı)
  - VM/user create flow'larına dokunmaz; sadece atama tablosu tutar
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("tenant_manager")

_FILE = Path("/var/lib/ankavm/tenants.json")
_lock = threading.RLock()

# Default kotalar — operatör tarafından override edilebilir
DEFAULT_QUOTA = {
    "vcpus":   16,
    "ram_mb":  32 * 1024,
    "disk_gb": 500,
    "vms_max": 25,
    "ips_max": 25,
}


# ── Persistence ──────────────────────────────────────────────────────────────
def _empty_state() -> dict:
    return {
        "tenants":      {},   # tenant_id -> tenant dict
        "user_tenant":  {},   # username   -> tenant_id
        "vm_tenant":    {},   # vm_id      -> tenant_id
    }


def _load() -> dict:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            # Migration / shape safety
            for k in ("tenants", "user_tenant", "vm_tenant"):
                data.setdefault(k, {})
            return data
    except Exception as e:
        log.warning("tenant state load fail: %s", e)
    return _empty_state()


def _save(state: dict) -> None:
    """Atomic write — tmp + rename."""
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _FILE)
    except Exception as e:
        log.warning("tenant state save fail: %s", e)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _merge_quota(custom: dict) -> dict:
    custom = custom or {}
    out = dict(DEFAULT_QUOTA)
    for k, v in custom.items():
        if k in out:
            try:
                out[k] = int(v)
            except Exception:
                pass
    return out


def _tenant_storage_path(tenant_id: str) -> str:
    return f"/var/lib/ankavm/tenants/{tenant_id}"


def _tenant_netns(tenant_id: str) -> str:
    return f"oxw-t-{tenant_id[:8]}"


# ── Public API ───────────────────────────────────────────────────────────────
def create_tenant(name: str, quota: Optional[dict] = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("tenant adı boş olamaz")
    tid = str(uuid.uuid4())
    tenant = {
        "id":                tid,
        "name":              name,
        "created_at":        int(time.time()),
        "quota":             _merge_quota(quota or {}),
        "network_namespace": _tenant_netns(tid),
        "storage_path":      _tenant_storage_path(tid),
    }
    with _lock:
        state = _load()
        # İsim çakışmasını uyar — ama bloklamayız (UUID'ler benzersiz)
        for t in state["tenants"].values():
            if t.get("name", "").lower() == name.lower():
                log.warning("tenant adı zaten kullanımda: %s", name)
                break
        state["tenants"][tid] = tenant
        _save(state)
    log.info("tenant oluşturuldu: %s (%s)", name, tid)
    return tenant


def delete_tenant(tenant_id: str, force: bool = False) -> dict:
    with _lock:
        state = _load()
        if tenant_id not in state["tenants"]:
            return {"ok": False, "error": "tenant bulunamadı"}
        # VM atamaları var mı?
        assigned_vms = [v for v, t in state["vm_tenant"].items() if t == tenant_id]
        if assigned_vms and not force:
            return {
                "ok":    False,
                "error": f"tenant'a {len(assigned_vms)} VM atanmış — önce silin veya force=true kullanın",
                "vms":   assigned_vms,
            }
        # User atamalarını da temizle
        users = [u for u, t in state["user_tenant"].items() if t == tenant_id]
        for u in users:
            state["user_tenant"].pop(u, None)
        for v in assigned_vms:
            state["vm_tenant"].pop(v, None)
        state["tenants"].pop(tenant_id, None)
        _save(state)
    log.info("tenant silindi: %s (force=%s)", tenant_id, force)
    return {"ok": True, "id": tenant_id, "removed_users": len(users), "removed_vms": len(assigned_vms)}


def list_tenants() -> list:
    with _lock:
        return list(_load()["tenants"].values())


def get_tenant(tenant_id: str) -> Optional[dict]:
    with _lock:
        return _load()["tenants"].get(tenant_id)


def update_quota(tenant_id: str, quota: dict) -> dict:
    with _lock:
        state = _load()
        t = state["tenants"].get(tenant_id)
        if not t:
            return {"ok": False, "error": "tenant bulunamadı"}
        merged = dict(t.get("quota", {}))
        for k, v in (quota or {}).items():
            if k in DEFAULT_QUOTA:
                try:
                    merged[k] = int(v)
                except Exception:
                    pass
        t["quota"] = merged
        _save(state)
        return {"ok": True, "quota": merged}


def assign_user_to_tenant(username: str, tenant_id: str) -> dict:
    username = (username or "").strip()
    if not username:
        return {"ok": False, "error": "kullanıcı adı boş"}
    with _lock:
        state = _load()
        if tenant_id not in state["tenants"]:
            return {"ok": False, "error": "tenant bulunamadı"}
        state["user_tenant"][username] = tenant_id
        _save(state)
    log.info("user %s → tenant %s", username, tenant_id)
    return {"ok": True}


def unassign_user(username: str) -> dict:
    with _lock:
        state = _load()
        removed = state["user_tenant"].pop(username, None)
        if removed:
            _save(state)
    return {"ok": True, "removed": bool(removed)}


def assign_vm_to_tenant(vm_id: str, tenant_id: str) -> dict:
    vm_id = str(vm_id)
    with _lock:
        state = _load()
        if tenant_id not in state["tenants"]:
            return {"ok": False, "error": "tenant bulunamadı"}
        state["vm_tenant"][vm_id] = tenant_id
        _save(state)
    log.info("vm %s → tenant %s", vm_id, tenant_id)
    return {"ok": True}


def unassign_vm(vm_id: str) -> dict:
    vm_id = str(vm_id)
    with _lock:
        state = _load()
        removed = state["vm_tenant"].pop(vm_id, None)
        if removed:
            _save(state)
    return {"ok": True, "removed": bool(removed)}


def get_user_tenant(username: str) -> Optional[str]:
    if not username:
        return None
    with _lock:
        return _load()["user_tenant"].get(username)


def get_vm_tenant(vm_id: str) -> Optional[str]:
    vm_id = str(vm_id)
    with _lock:
        return _load()["vm_tenant"].get(vm_id)


def list_tenant_vms(tenant_id: str) -> list:
    """tenant'a atanmış VM ID'leri."""
    with _lock:
        state = _load()
        return [v for v, t in state["vm_tenant"].items() if t == tenant_id]


def list_tenant_users(tenant_id: str) -> list:
    with _lock:
        state = _load()
        return [u for u, t in state["user_tenant"].items() if t == tenant_id]


def get_tenant_usage(tenant_id: str) -> dict:
    """
    Tenant'ın anlık kaynak kullanımını döner. vm_manager.list_vms() üzerinden
    hesaplar — modül yoksa sıfır döner (defensive).
    """
    usage = {
        "vcpus_used":   0,
        "ram_mb_used":  0,
        "disk_gb_used": 0,
        "vms_count":    0,
        "ips_count":    0,
    }
    try:
        with _lock:
            state = _load()
            vm_ids = {v for v, t in state["vm_tenant"].items() if t == tenant_id}
        if not vm_ids:
            return usage
        # vm_manager import — circular import'tan kaçınmak için lazy
        try:
            import vm_manager  # type: ignore
        except Exception:
            return usage
        try:
            all_vms = vm_manager.list_vms() or []
        except Exception:
            all_vms = []
        for vm in all_vms:
            vid = vm.get("id") or vm.get("uuid") or vm.get("name")
            if vid not in vm_ids and str(vid) not in vm_ids:
                continue
            usage["vms_count"] += 1
            try:
                usage["vcpus_used"] += int(vm.get("vcpus", 0) or 0)
            except Exception:
                pass
            try:
                usage["ram_mb_used"] += int(vm.get("memory_mb", vm.get("ram_mb", 0)) or 0)
            except Exception:
                pass
            try:
                usage["disk_gb_used"] += int(vm.get("disk_gb", 0) or 0)
            except Exception:
                pass
            # IP atamaları — varsa say
            ip_addrs = vm.get("ips") or vm.get("ip_addresses") or []
            if isinstance(ip_addrs, list):
                usage["ips_count"] += len(ip_addrs)
            elif vm.get("ip"):
                usage["ips_count"] += 1
    except Exception as e:
        log.debug("get_tenant_usage hata: %s", e)
    return usage


def check_quota(tenant_id: str, requested: Optional[dict] = None) -> dict:
    """
    Yeni bir kaynak isteği kotaya sığar mı? requested keys: vcpus, ram_mb,
    disk_gb (hepsi opsiyonel, eksikler 0 sayılır). Ayrıca vms_max ve ips_max
    kontrolü için 'vms', 'ips' alanları kabul edilir.
    """
    requested = requested or {}
    t = get_tenant(tenant_id)
    if not t:
        return {"allowed": False, "reason": "tenant bulunamadı"}
    q = t.get("quota", DEFAULT_QUOTA)
    u = get_tenant_usage(tenant_id)

    def _need(key: str) -> int:
        try:
            return int(requested.get(key, 0) or 0)
        except Exception:
            return 0

    checks = [
        ("vcpus",   "vcpus_used",   q.get("vcpus",   DEFAULT_QUOTA["vcpus"])),
        ("ram_mb",  "ram_mb_used",  q.get("ram_mb",  DEFAULT_QUOTA["ram_mb"])),
        ("disk_gb", "disk_gb_used", q.get("disk_gb", DEFAULT_QUOTA["disk_gb"])),
    ]
    for req_key, use_key, limit in checks:
        need = _need(req_key)
        if need <= 0:
            continue
        used = int(u.get(use_key, 0) or 0)
        if used + need > int(limit or 0):
            return {
                "allowed":   False,
                "reason":    f"{req_key} kotası aşılırdı ({used}+{need} > {limit})",
                "used":      used,
                "limit":     limit,
                "requested": need,
            }
    # Sayısal limitler
    if _need("vms") > 0 and u["vms_count"] + _need("vms") > int(q.get("vms_max", DEFAULT_QUOTA["vms_max"])):
        return {"allowed": False, "reason": "vms_max kotası aşılırdı"}
    if _need("ips") > 0 and u["ips_count"] + _need("ips") > int(q.get("ips_max", DEFAULT_QUOTA["ips_max"])):
        return {"allowed": False, "reason": "ips_max kotası aşılırdı"}
    return {"allowed": True, "reason": "ok"}


# CLI debug
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for t in list_tenants():
            print(t)
    elif cmd == "create":
        print(create_tenant(sys.argv[2] if len(sys.argv) > 2 else "default"))
    else:
        print("Usage: tenant_manager.py [list|create <name>]")






