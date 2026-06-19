"""
Boot Order Manager â€” DR scenario VM startup orchestration with dependencies.
"""
import json
import time
import logging
import threading
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("boot_order_manager")

DATA_DIR = Path("/var/lib/ankavm")
CONF_PATH = DATA_DIR / "boot_order.json"

_lock = threading.Lock()


def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONF_PATH.exists():
        CONF_PATH.write_text(json.dumps({"order": []}), encoding="utf-8")


def _load() -> dict:
    try:
        _ensure()
        return json.loads(CONF_PATH.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        log.error("_load: %s", e)
        return {"order": []}


def _save(state: dict):
    try:
        CONF_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("_save: %s", e)


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def set_boot_order(order_list: list) -> dict:
    """
    order_list: [{vm_id, priority:int, depends_on:[vm_id...], wait_for_ip:bool,
                  delay_sec:int}]
    """
    try:
        normalized = []
        for item in order_list or []:
            normalized.append({
                "vm_id": item["vm_id"],
                "priority": int(item.get("priority", 100)),
                "depends_on": list(item.get("depends_on") or []),
                "wait_for_ip": bool(item.get("wait_for_ip", False)),
                "delay_sec": int(item.get("delay_sec", 0)),
            })
        with _lock:
            _save({"order": normalized})
        return {"ok": True, "count": len(normalized)}
    except Exception as e:
        log.error("set_boot_order: %s", e)
        return {"ok": False, "error": str(e)}


def get_boot_order() -> list:
    try:
        return _load().get("order", [])
    except Exception as e:
        log.error("get_boot_order: %s", e)
        return []


def validate_dependencies() -> dict:
    """Topological cycle detection."""
    try:
        order = get_boot_order()
        ids = {o["vm_id"] for o in order}
        graph = {o["vm_id"]: list(o.get("depends_on") or []) for o in order}
        missing = []
        for vm, deps in graph.items():
            for d in deps:
                if d not in ids:
                    missing.append({"vm_id": vm, "missing_dep": d})

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in graph}
        cycles = []

        def dfs(n, stack):
            if color[n] == GRAY:
                cycles.append(stack + [n])
                return
            if color[n] == BLACK:
                return
            color[n] = GRAY
            for d in graph.get(n, []):
                if d in graph:
                    dfs(d, stack + [n])
            color[n] = BLACK

        for n in list(graph):
            if color[n] == WHITE:
                dfs(n, [])

        return {"ok": not cycles and not missing,
                "cycles": cycles, "missing": missing,
                "node_count": len(graph)}
    except Exception as e:
        log.error("validate_dependencies: %s", e)
        return {"ok": False, "error": str(e)}


def _vm_running(vm_id: str) -> bool:
    if libvirt is None:
        return False
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            return bool(dom.isActive())
        finally:
            conn.close()
    except Exception:
        return False


def _start_vm(vm_id: str) -> bool:
    if libvirt is None:
        return False
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            if not dom.isActive():
                dom.create()
            return True
        finally:
            conn.close()
    except Exception as e:
        log.warning("_start_vm %s: %s", vm_id, e)
        return False


def _wait_for_ip(vm_id: str, timeout: int = 120) -> bool:
    if libvirt is None:
        return False
    deadline = time.time() + timeout
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            while time.time() < deadline:
                try:
                    ifaces = dom.interfaceAddresses(
                        libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, 0)
                    for _, info in (ifaces or {}).items():
                        for addr in (info.get("addrs") or []):
                            if addr.get("addr"):
                                return True
                except Exception:
                    pass
                time.sleep(2)
            return False
        finally:
            conn.close()
    except Exception:
        return False


def execute_boot_sequence(dry_run: bool = False) -> dict:
    try:
        v = validate_dependencies()
        if not v.get("ok"):
            return {"ok": False, "error": "validation failed", "validation": v}
        order = sorted(get_boot_order(), key=lambda x: x.get("priority", 100))
        results = []
        for item in order:
            vm_id = item["vm_id"]
            entry = {"vm_id": vm_id, "priority": item["priority"]}
            # wait for deps
            for dep in item.get("depends_on") or []:
                if dry_run:
                    entry.setdefault("waited_for", []).append(dep)
                    continue
                if item.get("wait_for_ip"):
                    _wait_for_ip(dep, timeout=180)
                else:
                    # just wait until running
                    deadline = time.time() + 60
                    while time.time() < deadline and not _vm_running(dep):
                        time.sleep(2)
            if item.get("delay_sec"):
                if not dry_run:
                    time.sleep(item["delay_sec"])
                entry["delayed_sec"] = item["delay_sec"]
            if dry_run:
                entry["action"] = "would-start"
            else:
                entry["started"] = _start_vm(vm_id)
                if item.get("wait_for_ip"):
                    entry["got_ip"] = _wait_for_ip(vm_id, timeout=180)
            results.append(entry)
        return {"ok": True, "dry_run": bool(dry_run), "results": results}
    except Exception as e:
        log.error("execute_boot_sequence: %s", e)
        return {"ok": False, "error": str(e)}






