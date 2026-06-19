"""
ankavm Snapshot Orphan Cleanup
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Orphan snapshot tespit + temizleme. Boyut > limit, yaÅŸ > X gÃ¼n, broken chain vb.

API:
    list_all_snapshots() -> list      (tÃ¼m VM'ler iÃ§in)
    find_orphans(max_age_days=30) -> list
    cleanup_orphans(dry_run=True) -> dict
    get_policy() / set_policy(...)
"""

import os, json, time, subprocess, logging
from pathlib import Path
import threading

log = logging.getLogger("snapshot_cleanup")

_POLICY_FILE = Path("/var/lib/ankavm/snapshot_policy.json")
_LOCK = threading.Lock()

_DEFAULT_POLICY = {
    "enabled":           False,
    "max_age_days":      30,
    "max_snapshots_per_vm": 10,
    "max_total_size_gb": 100,
    "exclude_tags":      ["keep", "protected", "manual"],
    "exclude_vm_ids":    [],
    "schedule_cron":     "0 3 * * *",   # her gece 03:00
}


def get_policy() -> dict:
    if _POLICY_FILE.exists():
        try:
            return {**_DEFAULT_POLICY, **json.loads(_POLICY_FILE.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT_POLICY)


def set_policy(**kwargs) -> dict:
    with _LOCK:
        cfg = get_policy()
        for k, v in kwargs.items():
            if k in _DEFAULT_POLICY:
                cfg[k] = v
        _POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _POLICY_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return cfg


def _list_vms() -> list:
    """virsh list ile VM adlarÄ±nÄ± al."""
    try:
        r = subprocess.run(["virsh", "list", "--all", "--name"],
                           capture_output=True, text=True, timeout=10)
        return [n.strip() for n in r.stdout.splitlines() if n.strip()]
    except Exception:
        return []


def _list_snapshots(vm: str) -> list:
    """virsh snapshot-list ile snapshot'larÄ± al."""
    out = []
    try:
        r = subprocess.run(
            ["virsh", "snapshot-list", vm, "--metadata", "--tree"],
            capture_output=True, text=True, timeout=10
        )
        # XML format daha gÃ¼venilir â€” sadece liste lazÄ±m, name Ã§Ä±kar
        r2 = subprocess.run(
            ["virsh", "snapshot-list", vm, "--name"],
            capture_output=True, text=True, timeout=10
        )
        for name in r2.stdout.splitlines():
            name = name.strip()
            if not name:
                continue
            info = _get_snapshot_info(vm, name)
            out.append({"vm": vm, "name": name, **info})
    except Exception as e:
        log.warning("snapshot list hatasÄ± (%s): %s", vm, e)
    return out


def _get_snapshot_info(vm: str, snap: str) -> dict:
    """virsh snapshot-info parse."""
    info = {"created_ts": 0, "state": "", "description": ""}
    try:
        r = subprocess.run(
            ["virsh", "snapshot-info", vm, snap],
            capture_output=True, text=True, timeout=8
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Creation Time:"):
                ts = line.split(":", 1)[1].strip()
                try:
                    import datetime as _dt
                    info["created_ts"] = int(_dt.datetime.strptime(
                        ts.rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S"
                    ).timestamp())
                except Exception:
                    pass
            elif line.startswith("State:"):
                info["state"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                info["description"] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    return info


def list_all_snapshots() -> list:
    out = []
    for vm in _list_vms():
        out.extend(_list_snapshots(vm))
    return out


def find_orphans(max_age_days: int = None, max_per_vm: int = None) -> list:
    """Politikaya gÃ¶re orphan snapshot listesi dÃ¶ndÃ¼r."""
    cfg = get_policy()
    max_age_days = max_age_days or cfg["max_age_days"]
    max_per_vm   = max_per_vm   or cfg["max_snapshots_per_vm"]
    exclude_tags = set(cfg.get("exclude_tags", []))
    exclude_vms  = set(cfg.get("exclude_vm_ids", []))

    cutoff = time.time() - (max_age_days * 86400)
    snaps  = list_all_snapshots()
    orphans = []

    # YaÅŸ bazlÄ±
    for s in snaps:
        if s["vm"] in exclude_vms:
            continue
        if any(tag in (s.get("description") or "").lower() for tag in exclude_tags):
            continue
        if s["created_ts"] and s["created_ts"] < cutoff:
            orphans.append({**s, "reason": f"yaÅŸ > {max_age_days} gÃ¼n"})

    # VM baÅŸÄ± sayÄ± bazlÄ±
    by_vm = {}
    for s in snaps:
        by_vm.setdefault(s["vm"], []).append(s)
    for vm, lst in by_vm.items():
        if vm in exclude_vms:
            continue
        lst.sort(key=lambda x: x["created_ts"], reverse=True)
        # En yeniden en eskiye, max_per_vm'den sonrakiler orphan
        for old in lst[max_per_vm:]:
            if not any(o["vm"] == old["vm"] and o["name"] == old["name"] for o in orphans):
                orphans.append({**old, "reason": f"VM baÅŸÄ± limit ({max_per_vm}) aÅŸÄ±ldÄ±"})

    return orphans


def cleanup_orphans(dry_run: bool = True) -> dict:
    """Orphan'larÄ± sil. dry_run=True ise sadece listele."""
    orphans = find_orphans()
    deleted = []
    failed  = []
    for o in orphans:
        if dry_run:
            continue
        try:
            r = subprocess.run(
                ["virsh", "snapshot-delete", o["vm"], "--snapshotname", o["name"], "--metadata"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                deleted.append({"vm": o["vm"], "name": o["name"]})
            else:
                failed.append({"vm": o["vm"], "name": o["name"], "error": r.stderr.strip()})
        except Exception as e:
            failed.append({"vm": o["vm"], "name": o["name"], "error": str(e)})

    return {
        "dry_run":   dry_run,
        "found":     len(orphans),
        "deleted":   deleted,
        "failed":    failed,
        "orphans":   orphans if dry_run else [],
    }


def get_stats() -> dict:
    snaps = list_all_snapshots()
    orphans = find_orphans()
    cfg = get_policy()
    return {
        "total_snapshots": len(snaps),
        "orphan_count":    len(orphans),
        "by_vm":           {vm: len(lst) for vm, lst in
                            {s["vm"]: [s2 for s2 in snaps if s2["vm"] == s["vm"]]
                             for s in snaps}.items()},
        "policy":          cfg,
    }






