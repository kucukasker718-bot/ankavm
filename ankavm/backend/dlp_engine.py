"""
ankavm DLP at Hypervisor — pattern-based outbound traffic inspection
─────────────────────────────────────────────────────────────────────
Lightweight regex-based DLP for VM egress traffic.
Hooks into nftables NFLOG group → libpcap reader → match → block/alert.

DOES NOT inline-block (would require kernel module). Instead:
  - Periodic scan of recent NFLOG buffer
  - Match against DLP rules (regex/keyword)
  - Alert via event_logger + optional block via iptables drop list

Persistent rules: /var/lib/ankavm/dlp_rules.json
Match events:     /var/log/ankavm/dlp_events.jsonl
"""
from __future__ import annotations
import os, re, json, logging, subprocess, time, threading
from pathlib import Path

log = logging.getLogger("dlp_engine")
_RULES_FILE  = Path("/var/lib/ankavm/dlp_rules.json")
_EVENTS_FILE = Path("/var/log/ankavm/dlp_events.jsonl")
_lock = threading.Lock()


DEFAULT_RULES = [
    {"id": "credit_card", "name": "Credit Card Number",
     "pattern": r"\b(?:\d[ -]*?){13,19}\b", "action": "alert", "severity": "high"},
    {"id": "ssn_us",      "name": "US Social Security Number",
     "pattern": r"\b\d{3}-\d{2}-\d{4}\b", "action": "alert", "severity": "high"},
    {"id": "aws_key",     "name": "AWS Access Key",
     "pattern": r"AKIA[0-9A-Z]{16}", "action": "block", "severity": "critical"},
    {"id": "private_pem", "name": "PEM Private Key Header",
     "pattern": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
     "action": "block", "severity": "critical"},
    {"id": "jwt",         "name": "JWT Token",
     "pattern": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
     "action": "alert", "severity": "medium"},
    {"id": "tc_kimlik",   "name": "TC Kimlik No (TR)",
     "pattern": r"\b[1-9]\d{10}\b", "action": "alert", "severity": "high"},
]


def _load_rules() -> list:
    try:
        if _RULES_FILE.exists():
            return json.loads(_RULES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return list(DEFAULT_RULES)


def _save_rules(rules: list):
    _RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RULES_FILE.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def list_rules() -> list:
    return _load_rules()


def add_rule(rule: dict) -> dict:
    """Validate + add. Required: id, name, pattern; optional: action, severity."""
    if not rule.get("id") or not rule.get("pattern"):
        return {"ok": False, "error": "id ve pattern zorunlu"}
    try:
        re.compile(rule["pattern"])
    except re.error as e:
        return {"ok": False, "error": f"regex invalid: {e}"}
    with _lock:
        rules = _load_rules()
        rules = [r for r in rules if r["id"] != rule["id"]]
        rules.append({
            "id":       rule["id"],
            "name":     rule.get("name", rule["id"]),
            "pattern":  rule["pattern"],
            "action":   rule.get("action", "alert"),
            "severity": rule.get("severity", "medium"),
        })
        _save_rules(rules)
    return {"ok": True, "rule_id": rule["id"]}


def delete_rule(rule_id: str) -> dict:
    with _lock:
        rules = [r for r in _load_rules() if r["id"] != rule_id]
        _save_rules(rules)
    return {"ok": True}


def scan_text(text: str, vm_id: str = "") -> list:
    """Scan arbitrary text against all rules. Returns list of matches."""
    matches = []
    rules = _load_rules()
    for r in rules:
        try:
            for m in re.finditer(r["pattern"], text):
                evt = {
                    "ts":         int(time.time()),
                    "rule_id":    r["id"],
                    "rule_name":  r["name"],
                    "severity":   r["severity"],
                    "action":     r["action"],
                    "vm_id":      vm_id,
                    "matched":    m.group(0)[:32] + ("..." if len(m.group(0)) > 32 else ""),
                    "offset":     m.start(),
                }
                matches.append(evt)
                _log_event(evt)
        except Exception:
            pass
    return matches


def _log_event(evt: dict):
    try:
        _EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt) + "\n")
    except Exception:
        pass


def get_events(limit: int = 100, severity: str = None) -> list:
    """Return last N DLP events."""
    try:
        if not _EVENTS_FILE.exists():
            return []
        with _EVENTS_FILE.open(encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines[-limit*2:][::-1]:
            try:
                e = json.loads(line)
                if severity and e.get("severity") != severity:
                    continue
                out.append(e)
                if len(out) >= limit: break
            except Exception:
                pass
        return out
    except Exception:
        return []


def get_stats() -> dict:
    """Counters: total events, by severity."""
    by_sev = {}
    total  = 0
    try:
        if _EVENTS_FILE.exists():
            with _EVENTS_FILE.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        s = e.get("severity", "low")
                        by_sev[s] = by_sev.get(s, 0) + 1
                        total += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return {"total_events": total, "by_severity": by_sev, "rules_count": len(_load_rules())}






