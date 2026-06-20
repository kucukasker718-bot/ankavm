"""
ankavm Automation Engine — Auto-remediation + Policy-as-Code + Workflows
────────────────────────────────────────────────────────────────────────
Trigger -> condition -> action chains.
OPA/Rego style policy rules (NO arbitrary code execution - safe DSL only).
CloudEvents 1.0 event system.
"""

import json, time, uuid, threading, logging, re
from pathlib import Path

log = logging.getLogger("automation_engine")
_RULES    = Path("/var/lib/ankavm/automation_rules.json")
_POLICIES = Path("/var/lib/ankavm/policies.json")
_HISTORY  = Path("/var/lib/ankavm/automation_history.json")
_LOCK     = threading.Lock()


def _load(p, default):
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return default


def _save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


_VALID_ACTIONS = {
    "notify", "webhook", "vm_action", "scale_resources",
    "evacuate_vm", "create_snapshot", "tag_vm", "log", "siem_emit",
}


def list_rules() -> list:
    return _load(_RULES, [])


def create_rule(name: str, trigger: str, condition: dict = None,
                 actions: list = None, enabled: bool = True,
                 cooldown_sec: int = 60) -> dict:
    rule = {
        "id":           uuid.uuid4().hex[:12],
        "name":         name,
        "trigger":      trigger,
        "condition":    condition or {},
        "actions":      actions or [],
        "enabled":      enabled,
        "cooldown_sec": cooldown_sec,
        "last_fired":   None,
        "fire_count":   0,
        "created_at":   int(time.time()),
    }
    for a in rule["actions"]:
        if a.get("type") not in _VALID_ACTIONS:
            raise ValueError(f"Gecersiz action: {a.get('type')}")
    with _LOCK:
        rules = list_rules()
        rules.append(rule)
        _save(_RULES, rules)
    return rule


def delete_rule(rule_id: str) -> bool:
    with _LOCK:
        rules = list_rules()
        new = [r for r in rules if r["id"] != rule_id]
        if len(new) == len(rules):
            return False
        _save(_RULES, new)
    return True


def _check_condition(condition: dict, event: dict) -> bool:
    """Safe DSL comparison - NO code execution."""
    for key, expr in condition.items():
        val = event.get(key)
        if val is None:
            return False
        try:
            if isinstance(expr, str):
                if expr.startswith(">="):
                    if not (float(val) >= float(expr[2:])): return False
                elif expr.startswith("<="):
                    if not (float(val) <= float(expr[2:])): return False
                elif expr.startswith(">"):
                    if not (float(val) > float(expr[1:])): return False
                elif expr.startswith("<"):
                    if not (float(val) < float(expr[1:])): return False
                elif expr.startswith("=="):
                    if str(val) != expr[2:]: return False
                elif expr.startswith("!="):
                    if str(val) == expr[2:]: return False
                elif expr.startswith("contains:"):
                    if expr[9:] not in str(val): return False
                elif expr.startswith("regex:"):
                    if not re.search(expr[6:], str(val)): return False
                else:
                    if str(val) != expr: return False
            else:
                if val != expr: return False
        except (ValueError, TypeError):
            return False
    return True


def evaluate_event(event: dict) -> list:
    fired = []
    now = time.time()
    rules = list_rules()

    with _LOCK:
        for rule in rules:
            if not rule.get("enabled"):
                continue
            trig = rule.get("trigger", "")
            evt = event.get("trigger", event.get("event", ""))
            if trig != "*" and trig != evt:
                if trig.endswith(".*") and evt.startswith(trig[:-2] + "."):
                    pass
                else:
                    continue
            if rule.get("last_fired"):
                if now - rule["last_fired"] < rule.get("cooldown_sec", 60):
                    continue
            if not _check_condition(rule.get("condition", {}), event):
                continue
            rule["last_fired"] = int(now)
            rule["fire_count"] = rule.get("fire_count", 0) + 1
            fired.append(rule)
        if fired:
            _save(_RULES, rules)

    for rule in fired:
        for action in rule.get("actions", []):
            try:
                _execute_action(action, event, rule)
            except Exception as e:
                log.warning("automation action hatasi: %s", e)
        _record_history(rule, event)

    return fired


def _execute_action(action: dict, event: dict, rule: dict) -> None:
    a_type = action.get("type")
    params = action.get("params", {}) or {}

    def _run():
        try:
            if a_type == "notify":
                try:
                    import notifications
                    msg = params.get("msg", f"Automation rule {rule['name']} triggered")
                    notifications.send_notification(
                        message=msg,
                        channel=params.get("channel", "telegram"),
                        level=params.get("level", "info"),
                    )
                except Exception as e:
                    log.warning("notify action: %s", e)
            elif a_type == "webhook":
                try:
                    import webhook_manager
                    webhook_manager.trigger("automation.fired",
                                            {"rule": rule["name"], "event": event})
                except Exception as e:
                    log.warning("webhook action: %s", e)
            elif a_type == "vm_action":
                vm_id = event.get("vm_id") or params.get("vm_id")
                cmd = params.get("command", "reboot")
                if vm_id:
                    import subprocess as sp
                    sp.run(["virsh", cmd, vm_id], capture_output=True, timeout=15)
            elif a_type == "siem_emit":
                try:
                    import siem_exporter
                    siem_exporter.emit("automation.fired", "info",
                                        {"rule": rule["name"], **event})
                except Exception:
                    pass
            elif a_type == "log":
                try:
                    import event_logger
                    event_logger.log_event("automation",
                                            f"Rule '{rule['name']}' fired",
                                            level="info", details=event)
                except Exception:
                    pass
        except Exception as e:
            log.warning("action execute: %s", e)

    threading.Thread(target=_run, daemon=True).start()


def _record_history(rule: dict, event: dict):
    h = {
        "ts":        int(time.time()),
        "rule_id":   rule["id"],
        "rule_name": rule["name"],
        "event":     event,
    }
    with _LOCK:
        history = _load(_HISTORY, [])
        history.append(h)
        if len(history) > 500:
            history = history[-500:]
        _save(_HISTORY, history)


def get_history(limit: int = 50) -> list:
    history = _load(_HISTORY, [])
    return sorted(history, key=lambda x: x["ts"], reverse=True)[:limit]


# ── Policy-as-Code (lightweight OPA-style, SAFE DSL ONLY) ──────────────────
def list_policies() -> list:
    return _load(_POLICIES, _default_policies())


def _default_policies() -> list:
    return [
        {
            "id":      "max-snapshots",
            "name":    "VM max snapshot sayisi",
            "rule":    "if vm.snapshot_count > 10 then deny",
            "scope":   "vm.snapshot.create",
            "enabled": True,
        },
        {
            "id":      "tagged-vm-no-delete",
            "name":    "Production tag'li VM silinemez",
            "rule":    "if vm.tags contains 'production' then deny",
            "scope":   "vm.delete",
            "enabled": True,
        },
        {
            "id":      "cpu-overcommit-limit",
            "name":    "CPU overcommit 4x ten fazla olamaz",
            "rule":    "if host.cpu_overcommit_ratio > 4 then deny",
            "scope":   "vm.create",
            "enabled": True,
        },
    ]


def add_policy(name: str, rule: str, scope: str, enabled: bool = True) -> dict:
    policies = list_policies()
    p = {
        "id":         uuid.uuid4().hex[:10],
        "name":       name,
        "rule":       rule,
        "scope":      scope,
        "enabled":    enabled,
        "created_at": int(time.time()),
    }
    policies.append(p)
    _save(_POLICIES, policies)
    return p


def delete_policy(policy_id: str) -> bool:
    policies = list_policies()
    new = [p for p in policies if p["id"] != policy_id]
    if len(new) == len(policies):
        return False
    _save(_POLICIES, new)
    return True


def check_policy(scope: str, context: dict) -> dict:
    """
    Action oncesi policy kontrolu.
    Return: {allowed, denied_by, scope}
    """
    policies = [p for p in list_policies()
                if p.get("enabled") and (p.get("scope") == scope or p.get("scope") == "*")]
    denied = []
    for p in policies:
        if _interpret_rule(p["rule"], context):
            denied.append({"id": p["id"], "name": p["name"], "rule": p["rule"]})
    return {
        "allowed":   len(denied) == 0,
        "denied_by": denied,
        "scope":     scope,
    }


def _interpret_rule(rule_text: str, ctx: dict) -> bool:
    """
    SAFE rule interpreter. NO code execution. Only string parsing + comparison.
    Format: 'if X.Y OP VALUE then deny'  veya  'if X.Y contains "VAL" then deny'
    Returns True = deny applies.
    """
    if "then deny" not in rule_text:
        return False
    cond = rule_text.split("then deny")[0].replace("if ", "").strip()

    try:
        for op in [">=", "<=", "==", "!=", ">", "<"]:
            if op in cond:
                left, right = [s.strip() for s in cond.split(op, 1)]
                lv = _ctx_lookup(left, ctx)
                rv = right.strip("'\"")
                if lv is None:
                    return False
                try:
                    return _cmp(float(lv), float(rv), op)
                except ValueError:
                    return _cmp(str(lv), str(rv), op)
        if " contains " in cond:
            left, right = [s.strip() for s in cond.split(" contains ", 1)]
            lv = _ctx_lookup(left, ctx)
            rv = right.strip("'\"")
            if isinstance(lv, (list, tuple)):
                return rv in lv
            return rv in str(lv or "")
    except Exception as e:
        log.debug("policy interpret: %s - %s", rule_text, e)
    return False


def _ctx_lookup(key: str, ctx: dict):
    parts = key.split(".")
    cur = ctx
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
        if cur is None:
            return None
    return cur


def _cmp(a, b, op: str) -> bool:
    if op == ">":  return a > b
    if op == "<":  return a < b
    if op == ">=": return a >= b
    if op == "<=": return a <= b
    if op == "==": return a == b
    if op == "!=": return a != b
    return False






