"""
ankavm Maintenance Mode + Auto-Evacuation
─────────────────────────────────────────
Host'u bakım moduna al → VM'leri otomatik diğer host'lara taşı.
Tek host kurulumda VM'leri sadece pause + uyarı.

API:
    enter_maintenance(host=None, target_hosts=None) -> dict
    exit_maintenance(host=None) -> dict
    is_in_maintenance(host=None) -> bool
    get_status() -> dict
    list_evacuation_plan(host) -> list
"""

import os, json, time, threading, subprocess, logging
from pathlib import Path

log = logging.getLogger("maintenance_mode")

_STATE = Path("/var/lib/ankavm/maintenance.json")
_LOCK  = threading.Lock()


def _load() -> dict:
    if _STATE.exists():
        try:
            return json.loads(_STATE.read_text())
        except Exception:
            pass
    return {"hosts": {}}   # host → {since, reason, plan}


def _save(data: dict):
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def is_in_maintenance(host: str = None) -> bool:
    data = _load()
    if host:
        return host in data["hosts"]
    import socket
    return socket.gethostname() in data["hosts"]


def get_status(host: str = None) -> dict:
    data = _load()
    if not host:
        import socket
        host = socket.gethostname()
    entry = data["hosts"].get(host)
    return {
        "host":            host,
        "in_maintenance":  entry is not None,
        "details":         entry,
        "all_in_maintenance": list(data["hosts"].keys()),
    }


def _list_running_vms() -> list:
    """Bu host'taki çalışan VM'leri al."""
    try:
        r = subprocess.run(["virsh", "list", "--state-running", "--name"],
                           capture_output=True, text=True, timeout=10)
        return [v.strip() for v in r.stdout.splitlines() if v.strip()]
    except Exception:
        return []


def list_evacuation_plan(host: str = None, target_hosts: list = None) -> list:
    """
    Çalışan VM'leri target_hosts'a dağıt (round-robin).
    target_hosts boşsa tek host setup → sadece "graceful_shutdown" plan.
    """
    vms = _list_running_vms()
    plan = []
    if not target_hosts:
        # Tek host → graceful shutdown önerisi
        for vm in vms:
            plan.append({"vm": vm, "action": "graceful_shutdown",
                         "target": None,
                         "reason": "Cluster yok — VM'i durdur, bakım sonra başlat"})
    else:
        # Round-robin migrate
        for i, vm in enumerate(vms):
            target = target_hosts[i % len(target_hosts)]
            plan.append({"vm": vm, "action": "live_migrate",
                         "target": target,
                         "reason": f"Live migrate → {target}"})
    return plan


def enter_maintenance(reason: str = "Planned maintenance",
                       target_hosts: list = None,
                       dry_run: bool = False,
                       graceful_timeout: int = 60) -> dict:
    """
    Host'u maintenance moduna sok.
    1. Plan oluştur
    2. dry_run değilse: VM'leri evacuate et
    3. Host'u maintenance işaretle (yeni VM kabul etmez)
    """
    import socket
    host = socket.gethostname()

    data = _load()
    if host in data["hosts"]:
        return {"ok": False, "error": "Host zaten maintenance modunda",
                "since": data["hosts"][host].get("since")}

    plan = list_evacuation_plan(host, target_hosts)

    if dry_run:
        return {"ok": True, "dry_run": True, "plan": plan,
                "vm_count": len(plan)}

    # Execute plan
    results = []
    for step in plan:
        vm = step["vm"]
        if step["action"] == "live_migrate":
            try:
                r = subprocess.run(
                    ["virsh", "migrate", "--live", "--persistent", "--undefinesource",
                     vm, f"qemu+ssh://{step['target']}/system"],
                    capture_output=True, text=True, timeout=600
                )
                results.append({"vm": vm, "ok": r.returncode == 0,
                                "target": step["target"],
                                "error": r.stderr.strip() if r.returncode else ""})
            except Exception as e:
                results.append({"vm": vm, "ok": False, "error": str(e)})

        elif step["action"] == "graceful_shutdown":
            try:
                subprocess.run(["virsh", "shutdown", vm],
                               capture_output=True, timeout=10)
                # Wait for shutdown
                waited = 0
                while waited < graceful_timeout:
                    r = subprocess.run(["virsh", "domstate", vm],
                                       capture_output=True, text=True, timeout=5)
                    if "shut off" in r.stdout:
                        break
                    time.sleep(2)
                    waited += 2
                if waited >= graceful_timeout:
                    subprocess.run(["virsh", "destroy", vm],
                                   capture_output=True, timeout=10)
                    results.append({"vm": vm, "ok": True, "method": "forced_after_timeout"})
                else:
                    results.append({"vm": vm, "ok": True, "method": "graceful"})
            except Exception as e:
                results.append({"vm": vm, "ok": False, "error": str(e)})

    # Mark host as in maintenance
    with _LOCK:
        data = _load()
        data["hosts"][host] = {
            "since":          int(time.time()),
            "reason":         reason,
            "evacuated_vms":  [r["vm"] for r in results if r.get("ok")],
            "failed_vms":     [r["vm"] for r in results if not r.get("ok")],
            "plan":           plan,
        }
        _save(data)

    return {
        "ok":         True,
        "host":       host,
        "vm_count":   len(plan),
        "succeeded":  sum(1 for r in results if r.get("ok")),
        "failed":     sum(1 for r in results if not r.get("ok")),
        "results":    results,
    }


def exit_maintenance(host: str = None, auto_start: bool = False) -> dict:
    """
    Maintenance modundan çık. auto_start=True ise evacuated VM'leri geri başlat
    (basic — graceful_shutdown'ler için, migrate olanlar zaten karşı tarafta).
    """
    if not host:
        import socket
        host = socket.gethostname()

    with _LOCK:
        data = _load()
        entry = data["hosts"].pop(host, None)
        if entry is None:
            return {"ok": False, "error": "Host maintenance modunda değil"}
        _save(data)

    started = []
    if auto_start:
        for vm in entry.get("evacuated_vms", []):
            try:
                # Sadece bu host'ta tanımlıysa başlat (migrate edilenler artık burada yok)
                r = subprocess.run(["virsh", "domstate", vm],
                                   capture_output=True, text=True, timeout=5)
                if "shut off" in r.stdout:
                    subprocess.run(["virsh", "start", vm],
                                   capture_output=True, timeout=20)
                    started.append(vm)
            except Exception:
                pass

    return {
        "ok":              True,
        "host":            host,
        "was_since":       entry.get("since"),
        "duration_seconds": int(time.time() - entry.get("since", time.time())),
        "auto_started":    started,
    }






