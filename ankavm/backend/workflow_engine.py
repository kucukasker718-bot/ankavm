"""
ankavm Workflow Engine â€” Drag-drop multi-step automation
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Workflows: named sequences of steps, each with action + params +
on_success/on_fail routing. Steps may trigger VM actions, snapshots,
webhooks, or delays. No auto-loop / periodic execution â€” only
explicit run_workflow() calls.
"""

import json
import time
import uuid
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("workflow_engine")

_DATA_FILE    = Path("/var/lib/ankavm/workflows.json")
_HISTORY_FILE = Path("/var/lib/ankavm/workflow_history.json")
_lock         = threading.Lock()


# â”€â”€ persistence helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_workflows() -> list:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("workflow load fail: %s", e)
    return []


def _save_workflows(data: list) -> None:
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_DATA_FILE)
    except Exception as e:
        log.warning("workflow save fail: %s", e)


def _load_history() -> list:
    try:
        if _HISTORY_FILE.exists():
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("workflow history load fail: %s", e)
    return []


def _save_history(data: list) -> None:
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_HISTORY_FILE)
    except Exception as e:
        log.warning("workflow history save fail: %s", e)


# â”€â”€ valid step actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_VALID_ACTIONS = {
    "vm_action",     # virsh start/stop/reboot/suspend
    "snapshot",      # create snapshot on a VM
    "webhook",       # POST to a URL
    "delay",         # sleep N seconds
    "notify",        # internal notification
    "log",           # append to event_logger
}


def _validate_steps(steps: list) -> None:
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} must be a dict")
        action = step.get("action")
        if action not in _VALID_ACTIONS:
            raise ValueError(f"Step {i}: unknown action '{action}'. "
                             f"Allowed: {sorted(_VALID_ACTIONS)}")
        if not isinstance(step.get("params", {}), dict):
            raise ValueError(f"Step {i}: params must be a dict")


# â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_workflow(name: str, steps: list,
                    description: str = "",
                    enabled: bool = True) -> dict:
    """Create and persist a new workflow definition."""
    if not name:
        raise ValueError("name required")
    _validate_steps(steps)
    wf = {
        "id":          uuid.uuid4().hex[:12],
        "name":        name,
        "description": description,
        "steps":       steps,
        "enabled":     enabled,
        "created_at":  int(time.time()),
        "updated_at":  int(time.time()),
        "run_count":   0,
    }
    with _lock:
        workflows = _load_workflows()
        workflows.append(wf)
        _save_workflows(workflows)
    log.info("workflow created: %s (%s)", wf["id"], name)
    return wf


def list_workflows() -> list:
    with _lock:
        return _load_workflows()


def get_workflow(workflow_id: str) -> Optional[dict]:
    with _lock:
        for wf in _load_workflows():
            if wf["id"] == workflow_id:
                return wf
    return None


def delete_workflow(workflow_id: str) -> dict:
    with _lock:
        workflows = _load_workflows()
        new = [wf for wf in workflows if wf["id"] != workflow_id]
        if len(new) == len(workflows):
            return {"ok": False, "error": "not found"}
        _save_workflows(new)
    log.info("workflow deleted: %s", workflow_id)
    return {"ok": True, "deleted": workflow_id}


def run_workflow(workflow_id: str, dry_run: bool = False) -> dict:
    """
    Execute workflow steps sequentially.
    Returns per-step results. dry_run=True logs but does not act.
    No background loop â€” caller-driven only.
    """
    wf = get_workflow(workflow_id)
    if not wf:
        return {"ok": False, "error": "workflow not found"}
    if not wf.get("enabled"):
        return {"ok": False, "error": "workflow disabled"}

    run_id    = uuid.uuid4().hex[:10]
    started   = int(time.time())
    step_results = []
    overall_ok   = True

    steps = wf.get("steps", [])
    i = 0
    while 0 <= i < len(steps):
        step   = steps[i]
        action = step.get("action")
        params = step.get("params", {}) or {}
        step_start = time.time()
        step_ok    = False
        step_out   = {}

        try:
            if dry_run:
                step_ok = True
                step_out = {"dry_run": True, "action": action}
            elif action == "vm_action":
                vm_id   = params.get("vm_id", "")
                command = params.get("command", "reboot")
                if vm_id and command in ("start", "shutdown", "reboot",
                                         "suspend", "resume", "destroy"):
                    r = subprocess.run(
                        ["virsh", command, vm_id],
                        capture_output=True, text=True, timeout=30
                    )
                    step_ok  = r.returncode == 0
                    step_out = {"stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
                else:
                    step_ok  = False
                    step_out = {"error": "invalid vm_id or command"}
            elif action == "snapshot":
                vm_id    = params.get("vm_id", "")
                snap_name = params.get("name") or f"wf-{run_id}-step{i}"
                if vm_id:
                    r = subprocess.run(
                        ["virsh", "snapshot-create-as", vm_id, snap_name],
                        capture_output=True, text=True, timeout=60
                    )
                    step_ok  = r.returncode == 0
                    step_out = {"snapshot": snap_name,
                                "stdout": r.stdout.strip(),
                                "stderr": r.stderr.strip()}
                else:
                    step_ok  = False
                    step_out = {"error": "vm_id required"}
            elif action == "webhook":
                url  = params.get("url", "")
                body = params.get("body", {})
                if url:
                    try:
                        import webhook_manager
                        webhook_manager.trigger(
                            f"workflow.step.{i}",
                            {"workflow_id": workflow_id, "run_id": run_id,
                             "step": i, **body}
                        )
                        step_ok  = True
                        step_out = {"url": url}
                    except Exception as we:
                        step_ok  = False
                        step_out = {"error": str(we)}
                else:
                    step_ok  = False
                    step_out = {"error": "url required"}
            elif action == "delay":
                secs = min(int(params.get("seconds", 1)), 300)
                time.sleep(secs)
                step_ok  = True
                step_out = {"slept_seconds": secs}
            elif action == "notify":
                try:
                    import notifications
                    notifications.send_alert(
                        message=params.get("message", f"Workflow step {i} reached"),
                        level=params.get("level", "INFO"),
                        category="workflow",
                        details={"workflow_id": workflow_id, "run_id": run_id},
                    )
                    step_ok  = True
                    step_out = {}
                except Exception as ne:
                    step_ok  = True   # non-fatal
                    step_out = {"notify_error": str(ne)}
            elif action == "log":
                try:
                    import event_logger
                    event_logger.log_event(
                        "workflow",
                        params.get("message", f"Workflow {wf['name']} step {i}"),
                        level="info",
                        details={"workflow_id": workflow_id, "run_id": run_id},
                    )
                except Exception:
                    pass
                step_ok  = True
                step_out = {}
            else:
                step_ok  = False
                step_out = {"error": f"unknown action: {action}"}
        except Exception as ex:
            step_ok  = False
            step_out = {"error": str(ex)}
            log.warning("workflow %s step %d exception: %s", workflow_id, i, ex)

        elapsed = time.time() - step_start
        step_result = {
            "step":     i,
            "action":   action,
            "ok":       step_ok,
            "elapsed":  round(elapsed, 3),
            "output":   step_out,
        }
        step_results.append(step_result)

        if not step_ok:
            overall_ok = False
            on_fail = step.get("on_fail", "stop")
            if on_fail == "continue":
                i += 1
            elif on_fail == "stop":
                break
            elif isinstance(on_fail, int):
                i = on_fail
            else:
                break
        else:
            on_success = step.get("on_success", "next")
            if on_success == "next" or on_success is None:
                i += 1
            elif isinstance(on_success, int):
                i = on_success
            elif on_success == "stop":
                break
            else:
                i += 1

    # persist run record
    run_record = {
        "run_id":      run_id,
        "workflow_id": workflow_id,
        "workflow_name": wf["name"],
        "started_at":  started,
        "finished_at": int(time.time()),
        "dry_run":     dry_run,
        "ok":          overall_ok,
        "steps":       step_results,
    }
    with _lock:
        history = _load_history()
        history.append(run_record)
        if len(history) > 2000:
            history = history[-2000:]
        _save_history(history)
        # increment run counter
        workflows = _load_workflows()
        for wf2 in workflows:
            if wf2["id"] == workflow_id:
                wf2["run_count"] = wf2.get("run_count", 0) + 1
                wf2["last_run"]  = int(time.time())
                break
        _save_workflows(workflows)

    log.info("workflow %s run %s finished (ok=%s, steps=%d)",
             workflow_id, run_id, overall_ok, len(step_results))
    return run_record


def get_run_history(workflow_id: str, limit: int = 50) -> list:
    with _lock:
        history = _load_history()
    runs = [r for r in history if r.get("workflow_id") == workflow_id]
    return sorted(runs, key=lambda x: x.get("started_at", 0), reverse=True)[:limit]






