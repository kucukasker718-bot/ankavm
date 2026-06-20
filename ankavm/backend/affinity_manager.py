"""
ankavm Affinity / Anti-Affinity Rules
─────────────────────────────────────
VM placement kuralları:
  - "Bu 2 VM aynı host'ta olsun" (affinity)
  - "Bu 2 VM asla aynı host'ta olmasın" (anti-affinity, HA için)
  - "Bu VM sadece şu host(lar)'ta çalışabilir" (host pinning)
  - "Bu VM şu host(lar)'ta çalışamaz" (host exclusion)

API:
    add_rule(rule_type, vm_ids, ...) -> dict
    list_rules() -> list
    delete_rule(rule_id)
    check_placement(vm_id, target_host) -> {allowed, reason}
    get_violations() -> list  (mevcut yerleşim ihlalleri)
"""

import os, json, time, uuid, threading, logging
from pathlib import Path

log = logging.getLogger("affinity_manager")
_STORE = Path("/var/lib/ankavm/affinity_rules.json")
_LOCK  = threading.Lock()

_VALID_TYPES = {"affinity", "anti_affinity", "host_pin", "host_exclude"}


def _load() -> list:
    if not _STORE.exists():
        return []
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rules: list) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")


def list_rules() -> list:
    return _load()


def add_rule(rule_type: str, vm_ids: list = None, hosts: list = None,
             name: str = "", description: str = "", enforce: str = "must") -> dict:
    """
    rule_type: affinity | anti_affinity | host_pin | host_exclude
    enforce: must (sert kural, ihlal engellenir) | should (öneri, log atılır)
    """
    if rule_type not in _VALID_TYPES:
        raise ValueError(f"Geçersiz kural tipi: {rule_type}")

    rule = {
        "id":          uuid.uuid4().hex[:12],
        "type":        rule_type,
        "name":        name or f"{rule_type}-{int(time.time())}",
        "description": description,
        "vm_ids":      vm_ids or [],
        "hosts":       hosts or [],
        "enforce":     enforce if enforce in ("must", "should") else "must",
        "enabled":     True,
        "created_at":  int(time.time()),
    }

    # Validation
    if rule_type in ("affinity", "anti_affinity"):
        if len(rule["vm_ids"]) < 2:
            raise ValueError(f"{rule_type} kuralı en az 2 VM ID gerektirir")
    if rule_type in ("host_pin", "host_exclude"):
        if not rule["vm_ids"]:
            raise ValueError(f"{rule_type} kuralı VM ID(leri) gerektirir")
        if not rule["hosts"]:
            raise ValueError(f"{rule_type} kuralı en az 1 host gerektirir")

    with _LOCK:
        rules = _load()
        rules.append(rule)
        _save(rules)
    return rule


def delete_rule(rule_id: str) -> bool:
    with _LOCK:
        rules = _load()
        new   = [r for r in rules if r["id"] != rule_id]
        if len(new) == len(rules):
            return False
        _save(new)
    return True


def toggle_rule(rule_id: str, enabled: bool) -> dict:
    with _LOCK:
        rules = _load()
        for r in rules:
            if r["id"] == rule_id:
                r["enabled"] = bool(enabled)
                _save(rules)
                return r
    raise KeyError(rule_id)


def check_placement(vm_id: str, target_host: str,
                    vm_host_map: dict = None) -> dict:
    """
    VM'i target_host'a yerleştirmeden önce kontrol et.
    vm_host_map: {vm_id: host_name} — diğer VM'lerin mevcut konumu.
    """
    if vm_host_map is None:
        vm_host_map = {}
    rules = [r for r in _load() if r.get("enabled", True)]
    blocking = []
    warnings = []

    for r in rules:
        if vm_id not in r["vm_ids"]:
            continue
        t   = r["type"]
        sev = r.get("enforce", "must")

        if t == "host_pin":
            if target_host not in r["hosts"]:
                msg = f"VM '{vm_id}' sadece şu host'larda: {r['hosts']} — '{target_host}' izinli değil"
                (blocking if sev == "must" else warnings).append({"rule": r["name"], "reason": msg})

        elif t == "host_exclude":
            if target_host in r["hosts"]:
                msg = f"VM '{vm_id}' '{target_host}' host'undan dışlanmış"
                (blocking if sev == "must" else warnings).append({"rule": r["name"], "reason": msg})

        elif t == "affinity":
            partners = [v for v in r["vm_ids"] if v != vm_id]
            for p in partners:
                if p in vm_host_map and vm_host_map[p] != target_host:
                    msg = f"Affinity: '{p}' VM'i '{vm_host_map[p]}' host'unda — birlikte kalmalı"
                    (blocking if sev == "must" else warnings).append({"rule": r["name"], "reason": msg})

        elif t == "anti_affinity":
            partners = [v for v in r["vm_ids"] if v != vm_id]
            for p in partners:
                if p in vm_host_map and vm_host_map[p] == target_host:
                    msg = f"Anti-affinity: '{p}' VM'i zaten '{target_host}' host'unda — ayrılmalı"
                    (blocking if sev == "must" else warnings).append({"rule": r["name"], "reason": msg})

    return {
        "allowed":  len(blocking) == 0,
        "blocking": blocking,
        "warnings": warnings,
    }


def get_violations(vm_host_map: dict) -> list:
    """Mevcut yerleşimin kural ihlallerini bul."""
    violations = []
    for r in _load():
        if not r.get("enabled", True):
            continue
        t = r["type"]
        vms_in_play = [v for v in r["vm_ids"] if v in vm_host_map]
        if not vms_in_play:
            continue

        if t == "affinity":
            hosts = {vm_host_map[v] for v in vms_in_play}
            if len(hosts) > 1:
                violations.append({
                    "rule":  r["name"],
                    "type":  t,
                    "issue": f"VM'ler farklı host'larda: {sorted(hosts)}",
                    "vms":   vms_in_play,
                })

        elif t == "anti_affinity":
            from collections import Counter
            cnt = Counter(vm_host_map[v] for v in vms_in_play)
            dup = [h for h, c in cnt.items() if c > 1]
            if dup:
                violations.append({
                    "rule":  r["name"],
                    "type":  t,
                    "issue": f"Aynı host'ta birlikte: {dup}",
                    "vms":   vms_in_play,
                })

        elif t == "host_pin":
            allowed = set(r["hosts"])
            bad = [v for v in vms_in_play if vm_host_map[v] not in allowed]
            if bad:
                violations.append({
                    "rule":  r["name"],
                    "type":  t,
                    "issue": f"İzinli olmayan host'larda: {bad}",
                    "vms":   bad,
                })

        elif t == "host_exclude":
            forbidden = set(r["hosts"])
            bad = [v for v in vms_in_play if vm_host_map[v] in forbidden]
            if bad:
                violations.append({
                    "rule":  r["name"],
                    "type":  t,
                    "issue": f"Dışlanmış host'larda: {bad}",
                    "vms":   bad,
                })

    return violations






