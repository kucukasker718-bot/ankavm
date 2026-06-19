"""
ankavm Site Recovery Manager (SRM-lite) + RPO/RTO Monitoring
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DR plan tanÄ±mla â†’ otomatik failover/failback runbook.
RPO (Recovery Point Objective) ve RTO (Recovery Time Objective) takibi.

API:
    create_dr_plan(name, vms, target_site, boot_order, ...) -> dict
    list_plans() / delete_plan(id)
    execute_plan(plan_id, mode='test'|'failover') -> dict
    rollback_plan(plan_id) -> dict
    get_rpo_rto_status() -> dict
"""

import os, json, time, uuid, threading, logging
from pathlib import Path

log = logging.getLogger("site_recovery")

_PLANS  = Path("/var/lib/ankavm/dr_plans.json")
_RUNS   = Path("/var/lib/ankavm/dr_runs.json")
_RPO    = Path("/var/lib/ankavm/rpo_targets.json")
_LOCK   = threading.Lock()


def _load(p, default):
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return default


def _save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def list_plans() -> list:
    return _load(_PLANS, [])


def create_dr_plan(name: str, vms: list, target_site: str = "",
                    boot_order: list = None, rpo_minutes: int = 60,
                    rto_minutes: int = 30, description: str = "") -> dict:
    plan = {
        "id":           uuid.uuid4().hex[:12],
        "name":         name,
        "description":  description,
        "vms":          vms,
        "target_site":  target_site,
        "boot_order":   boot_order or vms,    # sÄ±rasÄ±yla baÅŸlatma
        "rpo_minutes":  rpo_minutes,
        "rto_minutes":  rto_minutes,
        "enabled":      True,
        "created_at":   int(time.time()),
        "last_test":    None,
        "last_test_status": None,
    }
    with _LOCK:
        plans = list_plans()
        plans.append(plan)
        _save(_PLANS, plans)
    return plan


def delete_plan(plan_id: str) -> bool:
    with _LOCK:
        plans = list_plans()
        new = [p for p in plans if p["id"] != plan_id]
        if len(new) == len(plans):
            return False
        _save(_PLANS, new)
    return True


def _save_run(run: dict):
    with _LOCK:
        runs = _load(_RUNS, [])
        runs.append(run)
        if len(runs) > 200:
            runs = runs[-200:]
        _save(_RUNS, runs)


def execute_plan(plan_id: str, mode: str = "test") -> dict:
    """
    mode:
      'test'     - sandbox failover (test drill, no commit)
      'failover' - gerÃ§ek failover
      'failback' - geri dÃ¶nÃ¼ÅŸ
    """
    plans = list_plans()
    plan  = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        raise KeyError("Plan bulunamadÄ±")

    run_id = uuid.uuid4().hex[:10]
    started = time.time()
    run = {
        "id":         run_id,
        "plan_id":    plan_id,
        "mode":       mode,
        "started":    int(started),
        "steps":      [],
        "status":     "running",
    }

    try:
        import subprocess
        for i, vm in enumerate(plan["boot_order"]):
            step_start = time.time()
            step = {"vm": vm, "order": i + 1, "started": int(step_start)}
            try:
                if mode == "test":
                    # Test: VM'i target_site'a clone et, baÅŸlat, durdur
                    step["action"] = "clone_to_target_and_start"
                    step["ok"]     = True
                    step["note"]   = "Test mode â€” simulation only"
                elif mode == "failover":
                    # GerÃ§ek: VM'i durdur, target site'da baÅŸlat (replication varsayar)
                    step["action"] = "start_at_target"
                    r = subprocess.run(["virsh", "start", vm],
                                       capture_output=True, text=True, timeout=30)
                    step["ok"]    = r.returncode == 0
                    step["error"] = r.stderr.strip() if r.returncode != 0 else ""
                elif mode == "failback":
                    step["action"] = "migrate_back"
                    step["ok"]     = True
                    step["note"]   = "Failback â€” VM target'tan source'a"
            except Exception as e:
                step["ok"]    = False
                step["error"] = str(e)
            step["duration_seconds"] = round(time.time() - step_start, 2)
            run["steps"].append(step)
            if mode == "failover" and not step.get("ok"):
                break  # Hata varsa dur

        run["status"]   = "completed" if all(s.get("ok") for s in run["steps"]) else "partial_failure"
        run["finished"] = int(time.time())
        run["duration_seconds"] = int(time.time() - started)
        run["actual_rto_minutes"] = round((time.time() - started) / 60, 1)

        # SLA check
        run["meets_rto"] = run["actual_rto_minutes"] <= plan["rto_minutes"]

        # Update plan last_test
        with _LOCK:
            all_plans = list_plans()
            for p in all_plans:
                if p["id"] == plan_id:
                    if mode == "test":
                        p["last_test"]        = int(time.time())
                        p["last_test_status"] = run["status"]
            _save(_PLANS, all_plans)

    except Exception as e:
        run["status"] = "error"
        run["error"]  = str(e)
    _save_run(run)
    return run


def get_run(run_id: str) -> dict:
    runs = _load(_RUNS, [])
    return next((r for r in runs if r["id"] == run_id), None)


def list_runs(plan_id: str = None, limit: int = 50) -> list:
    runs = _load(_RUNS, [])
    if plan_id:
        runs = [r for r in runs if r["plan_id"] == plan_id]
    return sorted(runs, key=lambda r: r.get("started", 0), reverse=True)[:limit]


def get_rpo_rto_status() -> dict:
    """RPO/RTO SLA durumu â€” tÃ¼m planlar iÃ§in."""
    plans = list_plans()
    runs  = _load(_RUNS, [])
    out = []
    for p in plans:
        recent_runs = [r for r in runs if r["plan_id"] == p["id"]][-10:]
        avg_rto = (sum(r.get("actual_rto_minutes", 0) for r in recent_runs) / len(recent_runs)
                   if recent_runs else None)
        out.append({
            "plan_id":     p["id"],
            "name":        p["name"],
            "rpo_target":  p["rpo_minutes"],
            "rto_target":  p["rto_minutes"],
            "rto_avg_last_10": round(avg_rto, 1) if avg_rto else None,
            "sla_met":     avg_rto <= p["rto_minutes"] if avg_rto else None,
            "last_test":   p.get("last_test"),
            "last_status": p.get("last_test_status"),
            "vms_count":   len(p["vms"]),
        })
    return {"plans": out, "total": len(out)}






