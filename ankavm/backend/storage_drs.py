"""
ankavm Storage DRS (Disk Resource Scheduler)
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Auto-migrate VM disks between storage pools based on I/O utilization.
All ops request-triggered (no background jobs).
"""

import json
import logging
import os
import re
import subprocess
import time

log = logging.getLogger("ankavm.storage_drs")

HIGH_WATERMARK = 80.0
LOW_WATERMARK  = 40.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(args, timeout=30):
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _to_bytes(s):
    """Convert virsh size string like '10.00 GiB' to bytes."""
    s = s.strip().upper()
    m = re.match(r"([\d.]+)\s*(GIB|GB|MIB|MB|KIB|KB|TIB|TB|B)?", s)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2) or "B"
    mult = {
        "B": 1,
        "KB": 1000, "KIB": 1024,
        "MB": 1000**2, "MIB": 1024**2,
        "GB": 1000**3, "GIB": 1024**3,
        "TB": 1000**4, "TIB": 1024**4,
    }.get(unit, 1)
    return int(val * mult)


def _bytes_to_gb(b):
    return round(b / (1024**3), 2)


def _get_pool_info_raw(pool_name):
    """Return raw pool-info dict from virsh."""
    r = _run(["virsh", "pool-info", pool_name])
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            info[k.strip().lower()] = v.strip()
    return info


def _get_pool_path(pool_name):
    """Return filesystem path of a storage pool."""
    try:
        r = _run(["virsh", "pool-dumpxml", pool_name])
        m = re.search(r"<path>(.*?)</path>", r.stdout)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _list_all_pools():
    """Return list of active pool names."""
    r = _run(["virsh", "pool-list", "--all"])
    pools = []
    for line in r.stdout.strip().splitlines()[2:]:
        parts = line.split()
        if parts and parts[1].lower() == "active":
            pools.append(parts[0])
    return pools


def _list_all_vms():
    """Return list of (vm_id, vm_name) tuples."""
    r = _run(["virsh", "list", "--all"])
    vms = []
    for line in r.stdout.strip().splitlines()[2:]:
        parts = line.split(None, 2)
        if len(parts) >= 2:
            vms.append((parts[0], parts[1]))
    return vms


def _get_vm_disks(vm_name):
    """Return list of {target, source_path} for a VM."""
    r = _run(["virsh", "domblklist", vm_name, "--details"])
    disks = []
    for line in r.stdout.strip().splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "disk" and parts[3] != "-":
            disks.append({"target": parts[2], "source_path": parts[3]})
    return disks


def _disk_size_bytes(disk_path):
    """Return disk image size in bytes via qemu-img."""
    try:
        r = subprocess.run(
            ["qemu-img", "info", "--output=json", disk_path],
            check=True, capture_output=True, text=True, timeout=15
        )
        info = json.loads(r.stdout)
        return info.get("virtual-size", 0)
    except Exception:
        return 0


def _pool_for_path(disk_path, pool_map):
    """Find which pool owns disk_path by checking path prefixes."""
    for pool_name, pool_path in pool_map.items():
        if pool_path and disk_path.startswith(pool_path):
            return pool_name
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_pool_stats(pool_name: str) -> dict:
    """capacity, allocated, available, utilization_pct, vm_count for one pool."""
    try:
        info = _get_pool_info_raw(pool_name)
        capacity  = _to_bytes(info.get("capacity", "0"))
        allocated = _to_bytes(info.get("allocation", "0"))
        available = _to_bytes(info.get("available", "0"))
        util_pct  = round((allocated / capacity * 100), 2) if capacity else 0.0
        pool_path = _get_pool_path(pool_name)

        vm_count = 0
        try:
            for _, vm_name in _list_all_vms():
                for disk in _get_vm_disks(vm_name):
                    if pool_path and disk["source_path"].startswith(pool_path):
                        vm_count += 1
                        break
        except Exception:
            pass

        return {
            "pool_name":       pool_name,
            "capacity_gb":     _bytes_to_gb(capacity),
            "allocated_gb":    _bytes_to_gb(allocated),
            "available_gb":    _bytes_to_gb(available),
            "utilization_pct": util_pct,
            "vm_count":        vm_count,
        }
    except subprocess.CalledProcessError as e:
        return {"pool_name": pool_name, "error": e.stderr.strip() or str(e)}
    except Exception as e:
        log.error("get_pool_stats(%s): %s", pool_name, e)
        return {"pool_name": pool_name, "error": str(e)}


def analyze_pools() -> dict:
    """
    List all active storage pools, compute utilization, flag imbalanced ones.
    Returns {pools: [...], overloaded: [...], underutilized: [...], imbalanced: bool}
    """
    try:
        pool_names = _list_all_pools()
        pools = [get_pool_stats(p) for p in pool_names]
        overloaded    = [p["pool_name"] for p in pools if not p.get("error") and p["utilization_pct"] > HIGH_WATERMARK]
        underutilized = [p["pool_name"] for p in pools if not p.get("error") and p["utilization_pct"] < LOW_WATERMARK]
        return {
            "pools":         pools,
            "overloaded":    overloaded,
            "underutilized": underutilized,
            "imbalanced":    bool(overloaded and underutilized),
        }
    except Exception as e:
        log.error("analyze_pools: %s", e)
        return {"pools": [], "overloaded": [], "underutilized": [], "imbalanced": False, "error": str(e)}


def get_recommendations() -> list:
    """
    Return list of {vm_id, vm_name, disk_path, source_pool, target_pool,
    disk_size_gb, reason} migration candidates to rebalance pools.
    """
    try:
        analysis = analyze_pools()
        if not analysis.get("imbalanced"):
            return []

        overloaded    = set(analysis["overloaded"])
        underutilized = set(analysis["underutilized"])

        pool_names = [p["pool_name"] for p in analysis["pools"] if not p.get("error")]
        pool_map   = {p: _get_pool_path(p) for p in pool_names}

        recommendations = []
        vms = _list_all_vms()

        for vm_id, vm_name in vms:
            try:
                disks = _get_vm_disks(vm_name)
            except Exception:
                continue
            for disk in disks:
                source_pool = _pool_for_path(disk["source_path"], pool_map)
                if source_pool not in overloaded:
                    continue
                target_pool = next(iter(underutilized), None)
                if not target_pool:
                    continue
                size_bytes = _disk_size_bytes(disk["source_path"])
                recommendations.append({
                    "vm_id":        vm_id,
                    "vm_name":      vm_name,
                    "disk_path":    disk["source_path"],
                    "source_pool":  source_pool,
                    "target_pool":  target_pool,
                    "disk_size_gb": _bytes_to_gb(size_bytes),
                    "reason":       f"Pool '{source_pool}' >{HIGH_WATERMARK}% used; '{target_pool}' <{LOW_WATERMARK}% used",
                })
        return recommendations
    except Exception as e:
        log.error("get_recommendations: %s", e)
        return []


def migrate_disk(vm_id: str, disk_path: str, target_pool: str) -> dict:
    """
    Migrate a VM disk to target_pool using virsh blockcopy.
    Returns {success, new_path, duration_seconds}.
    VM must be running or paused for blockcopy; falls back to offline
    qemu-img convert if VM is shut-off.
    """
    t_start = time.time()
    try:
        # Resolve VM name from ID
        r = _run(["virsh", "domname", vm_id])
        vm_name = r.stdout.strip()

        target_pool_path = _get_pool_path(target_pool)
        if not target_pool_path:
            return {"success": False, "error": f"Cannot resolve path for pool '{target_pool}'"}

        disk_basename = os.path.basename(disk_path)
        new_path      = os.path.join(target_pool_path, disk_basename)

        # Find disk target device (e.g. vda)
        disks = _get_vm_disks(vm_name)
        disk_target = None
        for d in disks:
            if d["source_path"] == disk_path:
                disk_target = d["target"]
                break

        if disk_target is None:
            return {"success": False, "error": f"Disk '{disk_path}' not found on VM '{vm_name}'"}

        # Check VM state
        state_r = _run(["virsh", "domstate", vm_name])
        vm_state = state_r.stdout.strip().lower()

        os.makedirs(target_pool_path, exist_ok=True)

        if vm_state in ("running", "paused"):
            _run([
                "virsh", "blockcopy", vm_name, disk_target,
                "--dest", new_path, "--format", "qcow2",
                "--wait", "--finish", "--pivot"
            ], timeout=7200)
        else:
            # Offline migration via qemu-img convert
            subprocess.run(
                ["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2",
                 disk_path, new_path],
                check=True, capture_output=True, text=True, timeout=7200
            )
            # Update domain XML
            _run(["virsh", "detach-disk", vm_name, disk_target, "--persistent"])
            _run([
                "virsh", "attach-disk", vm_name, new_path,
                disk_target, "--persistent", "--subdriver", "qcow2"
            ])

        # Refresh target pool
        try:
            _run(["virsh", "pool-refresh", target_pool])
        except Exception:
            pass

        return {
            "success":          True,
            "new_path":         new_path,
            "duration_seconds": round(time.time() - t_start, 2),
        }
    except subprocess.CalledProcessError as e:
        log.error("migrate_disk(%s, %s, %s): %s", vm_id, disk_path, target_pool, e.stderr)
        return {"success": False, "error": e.stderr.strip() or str(e), "duration_seconds": round(time.time() - t_start, 2)}
    except Exception as e:
        log.error("migrate_disk: %s", e)
        return {"success": False, "error": str(e), "duration_seconds": round(time.time() - t_start, 2)}


def auto_rebalance(dry_run: bool = True) -> dict:
    """
    Analyze pools, get recommendations, optionally execute migrations.
    Returns {migrated, skipped, errors, recommendations, dry_run}.
    """
    migrated = []
    skipped  = []
    errors   = []

    recommendations = get_recommendations()
    if not recommendations:
        return {"migrated": [], "skipped": [], "errors": [], "recommendations": [], "dry_run": dry_run}

    for rec in recommendations:
        if dry_run:
            skipped.append(rec)
            continue
        result = migrate_disk(rec["vm_id"], rec["disk_path"], rec["target_pool"])
        if result.get("success"):
            migrated.append({**rec, "new_path": result["new_path"], "duration_seconds": result["duration_seconds"]})
        else:
            errors.append({**rec, "error": result.get("error")})

    return {
        "migrated":        migrated,
        "skipped":         skipped,
        "errors":          errors,
        "recommendations": recommendations,
        "dry_run":         dry_run,
    }






