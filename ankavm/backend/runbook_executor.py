"""
ankavm Runbook Executor — auto-remediation engine.
───────────────────────────────────────────────────
Pre-approved runbooks fire when the anomaly detector raises a high-confidence
event. Each runbook has:
  - id, name, description
  - trigger: metric pattern + z-score threshold + cooldown
  - steps: ordered list of actions (api_call | shell | notify | vm_action)
  - approval: "auto" | "manual"  (only "auto" runs unattended)
  - max_runs_per_hour: safety cap

State:
  /var/lib/ankavm/runbooks.json        catalog
  /var/lib/ankavm/runbook_history.jsonl audit (append-only)

Integration: anomaly_detector.run_detection() may call
    runbook_executor.on_anomaly(anomaly_record)
which selects matching runbooks and executes them.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

try:
    from . import security_utils as _sec
except ImportError:
    import security_utils as _sec

log = logging.getLogger("ankavm.runbook")

_CATALOG = Path("/var/lib/ankavm/runbooks.json")
_HISTORY = Path("/var/lib/ankavm/runbook_history.jsonl")
_LOCK = threading.Lock()
_LAST_RUN: dict = {}  # runbook_id -> [timestamps]
_API_CALL_LOG: dict = {}  # runbook_id -> [timestamps] (per-step api_call quota)
_API_CALL_MAX_PER_HOUR = 120  # global per-runbook ceiling on api_call steps

# Shell step allowlist — only these absolute binaries may be invoked. Anything
# else is rejected. The runbook author may still pass arbitrary argv, but the
# program itself is constrained.
_SHELL_BIN_ALLOWLIST = (
    "/usr/bin/virsh",
    "/usr/sbin/virsh",
    "/usr/bin/systemctl",
    "/bin/systemctl",
    "/usr/bin/nft",
    "/usr/sbin/nft",
    "/usr/bin/journalctl",
    "/usr/bin/echo",
    "/bin/echo",
    "/usr/bin/true",
    "/bin/true",
)

DEFAULT_RUNBOOKS = [
    {
        "id": "rb-high-cpu-throttle",
        "name": "High CPU — throttle hot VMs",
        "description": "When host CPU sustains anomalous load, cap top consumer VMs to 60% via cgroups.",
        "trigger": {"metric_regex": r"^system\.cpu$", "min_z": 3.0, "cooldown_sec": 600},
        "steps": [
            {"type": "notify", "level": "WARNING",
             "message": "Auto-throttle triggered by anomaly"},
            {"type": "api_call", "method": "POST",
             "url": "http://127.0.0.1:8080/api/internal/throttle_top_vms",
             "allow_loopback": True, "allow_http": True,
             "json": {"cap_percent": 60, "duration_sec": 900}},
        ],
        "approval": "auto",
        "max_runs_per_hour": 4,
        "enabled": True,
    },
    {
        "id": "rb-mem-pressure-balloon",
        "name": "Memory pressure — balloon idle VMs",
        "description": "If host memory > 90% sustained anomalous, inflate balloon driver on idle VMs.",
        "trigger": {"metric_regex": r"^system\.mem$", "min_z": 3.0, "cooldown_sec": 600},
        "steps": [
            {"type": "notify", "level": "WARNING",
             "message": "Memory pressure — ballooning idle VMs"},
            {"type": "api_call", "method": "POST",
             "url": "http://127.0.0.1:8080/api/internal/balloon_idle_vms",
             "allow_loopback": True, "allow_http": True,
             "json": {"reclaim_mb": 1024}},
        ],
        "approval": "auto",
        "max_runs_per_hour": 4,
        "enabled": True,
    },
    {
        "id": "rb-disk-iops-spike",
        "name": "Disk IOPS spike — quiesce non-critical I/O",
        "description": "On per-VM IOPS anomaly, set blkio weight to lowest for tagged 'batch' VMs.",
        "trigger": {"metric_regex": r"^vm\..+\.iops$", "min_z": 3.5, "cooldown_sec": 300},
        "steps": [
            {"type": "api_call", "method": "POST",
             "url": "http://127.0.0.1:8080/api/internal/throttle_batch_io",
             "allow_loopback": True, "allow_http": True,
             "json": {"weight": 100}},
        ],
        "approval": "auto",
        "max_runs_per_hour": 6,
        "enabled": True,
    },
    {
        "id": "rb-vm-down-restart",
        "name": "VM unexpectedly stopped — auto-restart",
        "description": "If a VM with auto_restart=true stops outside a scheduled window, restart it.",
        "trigger": {"metric_regex": r"^vm\..+\.state_unexpected_stop$", "min_z": 0.0,
                    "cooldown_sec": 120},
        "steps": [
            {"type": "vm_action", "action": "start", "extract_vm_id_from": "metric_key"},
        ],
        "approval": "auto",
        "max_runs_per_hour": 3,
        "enabled": True,
    },
]


def _ensure():
    try:
        _CATALOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _load() -> list:
    _ensure()
    if not _CATALOG.exists():
        return list(DEFAULT_RUNBOOKS)
    try:
        return json.loads(_CATALOG.read_text(encoding="utf-8"))
    except Exception:
        return list(DEFAULT_RUNBOOKS)


def _save(items: list):
    _ensure()
    tmp = _CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    os.replace(tmp, _CATALOG)


def _audit(entry: dict):
    _ensure()
    entry["ts"] = time.time()
    try:
        with open(_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.debug("history write failed: %s", e)


def list_runbooks() -> list:
    return _load()


def get_runbook(rb_id: str) -> dict | None:
    for rb in _load():
        if rb.get("id") == rb_id:
            return rb
    return None


def upsert_runbook(rb: dict) -> dict:
    if "id" not in rb:
        raise ValueError("runbook requires id")
    items = _load()
    for i, existing in enumerate(items):
        if existing.get("id") == rb["id"]:
            items[i] = rb
            break
    else:
        items.append(rb)
    _save(items)
    return rb


def delete_runbook(rb_id: str) -> bool:
    items = _load()
    new = [r for r in items if r.get("id") != rb_id]
    if len(new) == len(items):
        return False
    _save(new)
    return True


def _within_quota(rb_id: str, max_per_hour: int) -> bool:
    now = time.time()
    with _LOCK:
        hist = _LAST_RUN.get(rb_id, [])
        hist = [t for t in hist if now - t < 3600]
        if len(hist) >= max_per_hour:
            _LAST_RUN[rb_id] = hist
            return False
        hist.append(now)
        _LAST_RUN[rb_id] = hist
        return True


def _within_cooldown(rb_id: str, cooldown_sec: int) -> bool:
    now = time.time()
    hist = _LAST_RUN.get(rb_id, [])
    return hist and (now - hist[-1] < cooldown_sec)


def _api_call_within_quota(rb_id: str) -> bool:
    """Per-runbook per-hour cap on api_call step invocations (SEC-022)."""
    now = time.time()
    with _LOCK:
        hist = _API_CALL_LOG.get(rb_id, [])
        hist = [t for t in hist if now - t < 3600]
        if len(hist) >= _API_CALL_MAX_PER_HOUR:
            _API_CALL_LOG[rb_id] = hist
            return False
        hist.append(now)
        _API_CALL_LOG[rb_id] = hist
        return True


def _run_step(step: dict, ctx: dict, rb_id: str = "") -> dict:
    t = step.get("type")
    if t == "notify":
        try:
            import notifications as _notif
            _notif.send_alert(
                message=step.get("message", "runbook notification"),
                level=step.get("level", "INFO"),
                category="runbook",
                details=ctx,
            )
            return {"ok": True, "type": t}
        except Exception as e:
            return {"ok": False, "type": t, "error": str(e)}
    if t == "shell":
        # SEC-022: shell steps restricted to allowlisted binaries.
        cmd = step.get("cmd")
        if not isinstance(cmd, list) or not cmd:
            return {"ok": False, "type": t, "error": "cmd must be a non-empty list"}
        if not all(isinstance(a, str) for a in cmd):
            return {"ok": False, "type": t, "error": "cmd args must be strings"}
        bin_path = cmd[0]
        if bin_path not in _SHELL_BIN_ALLOWLIST:
            return {"ok": False, "type": t,
                    "error": f"binary not on allowlist: {bin_path}",
                    "allowlist": list(_SHELL_BIN_ALLOWLIST)}
        # Reject shell metacharacters in every argv element.
        try:
            for a in cmd:
                _sec.safe_subprocess_arg(a)
        except _sec.SecurityValidationError as e:
            return {"ok": False, "type": t, "error": str(e)}
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=int(step.get("timeout", 30)))
            return {"ok": r.returncode == 0, "type": t,
                    "rc": r.returncode, "stdout": r.stdout[-2000:],
                    "stderr": r.stderr[-2000:]}
        except Exception as e:
            return {"ok": False, "type": t, "error": str(e)}
    if t == "api_call":
        # SEC-017: SSRF guard — block private/loopback URLs.
        # SEC-022: per-runbook hourly rate limit on api_call steps.
        url = step.get("url", "")
        try:
            allow_lb = bool(step.get("allow_loopback", False))
            allow_http = bool(step.get("allow_http", False)) or allow_lb
            safe_url = _sec.validate_external_url(
                url, allow_loopback=allow_lb, allow_http=allow_http,
            )
        except _sec.SecurityValidationError as e:
            return {"ok": False, "type": t, "error": str(e)}
        if rb_id and not _api_call_within_quota(rb_id):
            return {"ok": False, "type": t,
                    "error": f"api_call hourly quota ({_API_CALL_MAX_PER_HOUR}) exceeded"}
        try:
            data = None
            headers = {"Content-Type": "application/json"}
            if step.get("json") is not None:
                data = json.dumps(step["json"]).encode("utf-8")
            req = urllib.request.Request(
                safe_url, data=data,
                method=step.get("method", "GET"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=int(step.get("timeout", 15))) as resp:
                body = resp.read().decode("utf-8", "replace")[:4000]
                return {"ok": 200 <= resp.status < 300, "type": t,
                        "status": resp.status, "body": body}
        except Exception as e:
            return {"ok": False, "type": t, "error": str(e)}
    if t == "vm_action":
        # SEC-018: vm_id extracted from metric_key must be strictly validated
        # before passing as a subprocess argv element to virsh.
        vm_id = ctx.get("vm_id")
        if not vm_id and step.get("extract_vm_id_from") == "metric_key":
            mk = ctx.get("metric_key", "")
            parts = mk.split(".")
            if len(parts) >= 2 and parts[0] == "vm":
                vm_id = parts[1]
        action = step.get("action", "start")
        if action not in ("start", "shutdown", "reboot", "destroy", "suspend", "resume"):
            return {"ok": False, "type": t, "error": f"unsupported action: {action}"}
        try:
            vm_id = _sec.validate_vm_id(vm_id or "")
        except _sec.SecurityValidationError as e:
            return {"ok": False, "type": t, "error": str(e)}
        try:
            r = subprocess.run(["/usr/bin/virsh", action, vm_id],
                               capture_output=True, text=True, timeout=20)
            return {"ok": r.returncode == 0, "type": t, "vm_id": vm_id,
                    "action": action, "stdout": r.stdout, "stderr": r.stderr}
        except FileNotFoundError:
            # virsh installed under /usr/sbin on some distros
            try:
                r = subprocess.run(["/usr/sbin/virsh", action, vm_id],
                                   capture_output=True, text=True, timeout=20)
                return {"ok": r.returncode == 0, "type": t, "vm_id": vm_id,
                        "action": action, "stdout": r.stdout, "stderr": r.stderr}
            except Exception as e:
                return {"ok": False, "type": t, "error": str(e)}
        except Exception as e:
            return {"ok": False, "type": t, "error": str(e)}
    return {"ok": False, "type": t, "error": "unknown step type"}


def execute_runbook(rb_id: str, ctx: dict | None = None,
                    force: bool = False) -> dict:
    rb = get_runbook(rb_id)
    if not rb:
        return {"ok": False, "error": "runbook not found"}
    if not rb.get("enabled", True) and not force:
        return {"ok": False, "error": "disabled"}
    if not force:
        cd = int(rb.get("trigger", {}).get("cooldown_sec", 0))
        if cd and _within_cooldown(rb_id, cd):
            return {"ok": False, "error": "cooldown active"}
        if not _within_quota(rb_id, int(rb.get("max_runs_per_hour", 10))):
            return {"ok": False, "error": "hourly quota exceeded"}
    ctx = ctx or {}
    results = []
    for step in rb.get("steps", []):
        results.append(_run_step(step, ctx, rb_id=rb_id))
    summary = {
        "ok": all(s.get("ok") for s in results),
        "runbook_id": rb_id,
        "steps": results,
        "ctx": ctx,
        "forced": force,
    }
    _audit({"event": "execute", **summary})
    return summary


def on_anomaly(anomaly: dict) -> list:
    """Called by anomaly_detector when a new anomaly is recorded.
    Returns a list of executed runbook ids."""
    import re
    out = []
    metric_key = anomaly.get("metric_key", "")
    z = float(anomaly.get("z_score", 0.0))
    for rb in _load():
        if not rb.get("enabled", True):
            continue
        if rb.get("approval", "auto") != "auto":
            continue
        trig = rb.get("trigger", {})
        pat = trig.get("metric_regex")
        if pat and not re.match(pat, metric_key):
            continue
        if z < float(trig.get("min_z", 0.0)):
            continue
        ctx = {"metric_key": metric_key, "z_score": z,
               "value": anomaly.get("current_value")}
        res = execute_runbook(rb["id"], ctx)
        if res.get("ok") or "cooldown" not in str(res.get("error", "")):
            out.append(rb["id"])
    return out


def history(limit: int = 100) -> list:
    if not _HISTORY.exists():
        return []
    try:
        with open(_HISTORY, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception as e:
        log.debug("history read: %s", e)
        return []






