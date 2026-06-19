"""
ankavm Alert Correlation Engine
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Ã‡ok sayÄ±da alert â†’ tek incident. Same VM/host/category 5 dk window'da grupla.

API:
    correlate(alerts) -> list  (gruplandÄ±rÄ±lmÄ±ÅŸ incidents)
    add_rule(pattern, group_by, window_sec) -> dict
    list_incidents(active_only=True) -> list
    resolve_incident(incident_id) -> bool
"""

import json, time, uuid, threading, logging
from pathlib import Path
from collections import defaultdict

log = logging.getLogger("alert_correlation")

_INCIDENTS = Path("/var/lib/ankavm/incidents.json")
_RULES     = Path("/var/lib/ankavm/correlation_rules.json")
_LOCK      = threading.Lock()


_DEFAULT_RULES = [
    {"id": "vm-down-storm",   "pattern": "vm.*",         "group_by": "host",     "window_sec": 300},
    {"id": "high-cpu-cluster","pattern": "host.cpu.high","group_by": "category", "window_sec": 600},
    {"id": "disk-fail-host",  "pattern": "*disk*",       "group_by": "host",     "window_sec": 900},
    {"id": "auth-bruteforce", "pattern": "auth.fail*",   "group_by": "source_ip","window_sec": 300},
]


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def _save(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def list_rules() -> list:
    return _load(_RULES, list(_DEFAULT_RULES))


def add_rule(pattern: str, group_by: str, window_sec: int,
             rule_id: str = None) -> dict:
    rules = list_rules()
    r = {
        "id":         rule_id or uuid.uuid4().hex[:10],
        "pattern":    pattern,
        "group_by":   group_by,
        "window_sec": window_sec,
        "enabled":    True,
        "created_at": int(time.time()),
    }
    rules.append(r)
    _save(_RULES, rules)
    return r


def delete_rule(rule_id: str) -> bool:
    rules = list_rules()
    new = [r for r in rules if r["id"] != rule_id]
    if len(new) == len(rules):
        return False
    _save(_RULES, new)
    return True


def _match_pattern(event: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(event, pattern)


def correlate(alerts: list) -> list:
    """
    alerts: [{event, severity, ts, host, vm, category, source_ip, ...}]
    Return: [{incident_id, alerts, count, first_seen, last_seen, common_attrs}]
    """
    rules = [r for r in list_rules() if r.get("enabled", True)]
    incidents = []
    matched_indexes = set()

    for rule in rules:
        groups = defaultdict(list)
        for i, a in enumerate(alerts):
            if i in matched_indexes:
                continue
            if not _match_pattern(a.get("event", ""), rule["pattern"]):
                continue
            key = a.get(rule["group_by"], "_default")
            groups[key].append((i, a))

        for key, items in groups.items():
            if len(items) < 2:
                continue
            # Window check
            ts_list = [a.get("ts", 0) for _, a in items]
            if max(ts_list) - min(ts_list) > rule["window_sec"]:
                # Window dÄ±ÅŸÄ± â€” alt-grupla
                items.sort(key=lambda x: x[1].get("ts", 0))
                window_groups = []
                current = [items[0]]
                for it in items[1:]:
                    if it[1].get("ts", 0) - current[-1][1].get("ts", 0) <= rule["window_sec"]:
                        current.append(it)
                    else:
                        if len(current) >= 2:
                            window_groups.append(current)
                        current = [it]
                if len(current) >= 2:
                    window_groups.append(current)
            else:
                window_groups = [items]

            for grp in window_groups:
                inc_id = uuid.uuid4().hex[:12]
                grp_alerts = [a for _, a in grp]
                incidents.append({
                    "id":         inc_id,
                    "rule":       rule["id"],
                    "pattern":    rule["pattern"],
                    "group_by":   rule["group_by"],
                    "group_value": key,
                    "count":      len(grp_alerts),
                    "first_seen": min(a.get("ts", 0) for a in grp_alerts),
                    "last_seen":  max(a.get("ts", 0) for a in grp_alerts),
                    "severity":   max(_sev(a.get("severity", "info")) for a in grp_alerts),
                    "alerts":     grp_alerts,
                })
                matched_indexes.update(i for i, _ in grp)

    # EÅŸleÅŸmeyen alert'leri tek alert incident olarak ekle
    for i, a in enumerate(alerts):
        if i not in matched_indexes:
            incidents.append({
                "id":         uuid.uuid4().hex[:12],
                "rule":       None,
                "pattern":    a.get("event", ""),
                "group_by":   None,
                "group_value": None,
                "count":      1,
                "first_seen": a.get("ts", 0),
                "last_seen":  a.get("ts", 0),
                "severity":   _sev(a.get("severity", "info")),
                "alerts":     [a],
            })
    return incidents


def _sev(level: str) -> int:
    return {"debug": 1, "info": 2, "notice": 3, "warn": 4,
            "warning": 4, "error": 5, "critical": 6, "alert": 7}.get(level, 2)


def list_incidents(active_only: bool = True) -> list:
    incidents = _load(_INCIDENTS, [])
    if active_only:
        return [i for i in incidents if not i.get("resolved")]
    return incidents


def add_incident(incident: dict):
    with _LOCK:
        items = _load(_INCIDENTS, [])
        items.append(incident)
        # Keep last 1000
        if len(items) > 1000:
            items = items[-1000:]
        _save(_INCIDENTS, items)


def resolve_incident(incident_id: str) -> bool:
    with _LOCK:
        items = _load(_INCIDENTS, [])
        for i in items:
            if i["id"] == incident_id:
                i["resolved"]    = True
                i["resolved_at"] = int(time.time())
                _save(_INCIDENTS, items)
                return True
    return False






