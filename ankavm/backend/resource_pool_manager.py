"""ankavm Resource Pool Manager — CPU/RAM quotas per VM group.
Storage: /var/lib/ankavm/resource_pools.json
"""
import json, uuid, threading
from datetime import datetime, timezone
from pathlib import Path

_POOLS_FILE = "/var/lib/ankavm/resource_pools.json"
_lock = threading.Lock()


def _load():
    try:
        p = Path(_POOLS_FILE)
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return []


def _save(data):
    Path(_POOLS_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(_POOLS_FILE).write_text(json.dumps(data, indent=2))


def list_pools():
    with _lock:
        return _load()


def create_pool(name, description="", cpu_limit_pct=100, ram_limit_mb=0):
    pool = {
        "id": str(uuid.uuid4()),
        "name": str(name).strip(),
        "description": str(description).strip(),
        "vm_ids": [],
        "cpu_limit_pct": int(cpu_limit_pct),
        "ram_limit_mb": int(ram_limit_mb),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        pools = _load()
        pools.append(pool)
        _save(pools)
    return pool


def update_pool(pool_id, **kwargs):
    allowed = {"name", "description", "cpu_limit_pct", "ram_limit_mb"}
    with _lock:
        pools = _load()
        for p in pools:
            if p["id"] == pool_id:
                for k, v in kwargs.items():
                    if k in allowed:
                        p[k] = v
                _save(pools)
                return p
    return None


def delete_pool(pool_id):
    with _lock:
        pools = _load()
        new_pools = [p for p in pools if p["id"] != pool_id]
        if len(new_pools) == len(pools):
            return False
        _save(new_pools)
    return True


def add_vm_to_pool(pool_id, vm_id):
    vm_id = str(vm_id)
    with _lock:
        pools = _load()
        # Remove vm from any existing pool first
        for p in pools:
            if vm_id in p["vm_ids"]:
                p["vm_ids"].remove(vm_id)
        for p in pools:
            if p["id"] == pool_id:
                if vm_id not in p["vm_ids"]:
                    p["vm_ids"].append(vm_id)
                _save(pools)
                return True
    return False


def remove_vm_from_pool(pool_id, vm_id):
    vm_id = str(vm_id)
    with _lock:
        pools = _load()
        for p in pools:
            if p["id"] == pool_id and vm_id in p["vm_ids"]:
                p["vm_ids"].remove(vm_id)
                _save(pools)
                return True
    return False


def get_vm_pool(vm_id):
    vm_id = str(vm_id)
    with _lock:
        for p in _load():
            if vm_id in p["vm_ids"]:
                return p
    return None


# ── v2.5.6 — Reservations (minimum guaranteed resources per pool) ─────────────
def set_reservations(pool_id, vcpu_min=0, ram_mb_min=0):
    """
    Pool için minimum garantili kaynak rezervasyonu ayarla.
    Placement / scheduler bu değerleri dikkate alarak VM yerleştirir.

    Returns: güncellenmiş pool dict (None — pool yoksa).
    """
    try:
        vcpu_min   = max(0, int(vcpu_min or 0))
        ram_mb_min = max(0, int(ram_mb_min or 0))
    except Exception:
        return None
    with _lock:
        pools = _load()
        for p in pools:
            if p["id"] == pool_id:
                p["vcpu_reservation"]   = vcpu_min
                p["ram_mb_reservation"] = ram_mb_min
                p["reservation_updated"] = datetime.now(timezone.utc).isoformat()
                _save(pools)
                return p
    return None


def get_reservations(pool_id):
    """Pool rezervasyonlarını döner — yoksa sıfır."""
    with _lock:
        for p in _load():
            if p["id"] == pool_id:
                return {
                    "pool_id":            pool_id,
                    "vcpu_reservation":   int(p.get("vcpu_reservation", 0) or 0),
                    "ram_mb_reservation": int(p.get("ram_mb_reservation", 0) or 0),
                    "updated":            p.get("reservation_updated"),
                }
    return None






