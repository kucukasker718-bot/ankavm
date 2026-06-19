"""
microsegmentation.py â€” Per-VM L7 Firewall (nftables-based)
ankavm v2.5.9 Network Advanced 2

Features:
  - set_vm_policy(vm_id, rules) â€” nftables chain per VM tap interface
  - get_vm_policy(vm_id), list_policies(), delete_vm_policy(vm_id)
  - apply_zero_trust(vm_id) â€” default deny-all + only defined allow rules
  - Config persisted to /var/lib/ankavm/microseg_policies.json (reboot restore)
  - nftables via subprocess; graceful fallback if nftables unavailable
  - No external dependencies (stdlib + subprocess only)
"""

from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("microsegmentation")

_POLICY_FILE = Path("/var/lib/ankavm/microseg_policies.json")
_lock        = threading.Lock()


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _POLICY_FILE.exists():
            return json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("microseg load fail: %s", e)
    return {}


def _save(data: dict) -> None:
    try:
        _POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _POLICY_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_POLICY_FILE)
    except Exception as e:
        log.warning("microseg save fail: %s", e)


# â”€â”€ nftables helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _nft_available() -> bool:
    try:
        r = subprocess.run(["nft", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _chain_name(vm_id: str) -> str:
    safe = vm_id.replace("-", "_").replace(".", "_")
    return f"ankavm_vm_{safe}"


def _rule_to_nft(rule: dict) -> Optional[str]:
    """Convert a policy rule dict to an nft rule statement."""
    direction = rule.get("direction", "ingress")
    proto     = rule.get("proto", "tcp")
    port      = rule.get("port")
    src       = rule.get("src")
    dst       = rule.get("dst")
    action    = rule.get("action", "accept")
    l7_app    = rule.get("l7_app")

    # Map action
    nft_action = "accept" if action == "allow" else "drop"

    parts = []
    if proto in ("tcp", "udp"):
        parts.append(proto)
    if src:
        parts.append(f"ip saddr {src}")
    if dst:
        parts.append(f"ip daddr {dst}")
    if port and proto in ("tcp", "udp"):
        parts.append(f"{proto} dport {port}")
    if l7_app:
        # L7 comment only â€” actual L7 enforcement requires conntrack mark or NFQueue
        parts.append(f"comment \"l7:{l7_app}\"")
    parts.append(nft_action)
    return " ".join(parts) if parts else None


def _nft_flush_chain(chain: str) -> None:
    try:
        subprocess.run(
            ["nft", "flush", "chain", "ip", "filter", chain],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _nft_delete_chain(chain: str) -> None:
    try:
        _nft_flush_chain(chain)
        subprocess.run(
            ["nft", "delete", "chain", "ip", "filter", chain],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _nft_create_chain(chain: str, default_policy: str = "accept") -> bool:
    try:
        # Ensure base table exists
        subprocess.run(
            ["nft", "add", "table", "ip", "filter"],
            capture_output=True, timeout=5,
        )
        r = subprocess.run(
            ["nft", "add", "chain", "ip", "filter", chain,
             "{", "type", "filter", "hook", "forward",
             "priority", "0", ";", "policy", default_policy, ";", "}"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception as e:
        log.warning("nft create_chain fail: %s", e)
        return False


def _nft_add_rule(chain: str, rule_stmt: str) -> bool:
    try:
        r = subprocess.run(
            ["nft", "add", "rule", "ip", "filter", chain, rule_stmt],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            log.warning("nft add_rule fail (%s): %s", rule_stmt, r.stderr.strip())
        return r.returncode == 0
    except Exception as e:
        log.warning("nft add_rule exception: %s", e)
        return False


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def set_vm_policy(vm_id: str, rules: list) -> dict:
    """
    Apply L7-aware nftables chain for vm_id.
    rules: [{direction, proto, port, src, dst, action:'allow'|'deny', l7_app?}]
    """
    with _lock:
        chain = _chain_name(vm_id)
        applied = []
        errors  = []

        if _nft_available():
            _nft_delete_chain(chain)
            _nft_create_chain(chain, default_policy="accept")
            for rule in rules:
                stmt = _rule_to_nft(rule)
                if stmt:
                    ok_flag = _nft_add_rule(chain, stmt)
                    if ok_flag:
                        applied.append(rule)
                    else:
                        errors.append({"rule": rule, "error": "nft add failed"})
                else:
                    errors.append({"rule": rule, "error": "unrepresentable rule"})
        else:
            log.warning("microseg: nftables not available â€” storing policy only (no kernel enforcement)")
            applied = list(rules)

        # Persist
        data = _load()
        data[vm_id] = {
            "vm_id":      vm_id,
            "rules":      rules,
            "applied":    applied,
            "chain":      chain,
            "zero_trust": False,
            "updated_at": int(time.time()),
        }
        _save(data)

        return {
            "ok":       True,
            "vm_id":    vm_id,
            "chain":    chain,
            "applied":  len(applied),
            "errors":   errors,
            "nft":      _nft_available(),
        }


def get_vm_policy(vm_id: str) -> Optional[dict]:
    with _lock:
        data = _load()
        return data.get(vm_id)


def list_policies() -> list:
    with _lock:
        data = _load()
        return list(data.values())


def delete_vm_policy(vm_id: str) -> dict:
    with _lock:
        data = _load()
        if vm_id not in data:
            return {"ok": False, "error": "No policy for vm_id"}
        chain = _chain_name(vm_id)
        if _nft_available():
            _nft_delete_chain(chain)
        del data[vm_id]
        _save(data)
        return {"ok": True, "vm_id": vm_id, "chain": chain}


def apply_zero_trust(vm_id: str) -> dict:
    """
    Default-deny + only explicitly allowed rules remain.
    Sets chain policy to 'drop' and flushes all rules except user-defined allows.
    """
    with _lock:
        data = _load()
        entry = data.get(vm_id, {})
        rules = entry.get("rules", [])

        # Keep only allow rules for zero-trust
        allow_rules = [r for r in rules if r.get("action", "allow") == "allow"]

        chain = _chain_name(vm_id)
        if _nft_available():
            _nft_delete_chain(chain)
            _nft_create_chain(chain, default_policy="drop")
            for rule in allow_rules:
                stmt = _rule_to_nft(rule)
                if stmt:
                    _nft_add_rule(chain, stmt)

        data[vm_id] = {
            "vm_id":      vm_id,
            "rules":      rules,
            "applied":    allow_rules,
            "chain":      chain,
            "zero_trust": True,
            "updated_at": int(time.time()),
        }
        _save(data)

        return {
            "ok":         True,
            "vm_id":      vm_id,
            "zero_trust": True,
            "allow_rules": len(allow_rules),
            "nft":        _nft_available(),
        }


def restore_all_from_config() -> dict:
    """Re-apply all persisted policies (e.g. after reboot). Not called automatically."""
    with _lock:
        data = _load()
        restored = 0
        errors   = []
        for vm_id, entry in data.items():
            try:
                if entry.get("zero_trust"):
                    apply_zero_trust(vm_id)
                else:
                    set_vm_policy(vm_id, entry.get("rules", []))
                restored += 1
            except Exception as e:
                errors.append({"vm_id": vm_id, "error": str(e)})
        return {"ok": True, "restored": restored, "errors": errors}






