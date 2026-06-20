"""
drift_capacity.py — Config Drift Detection + Capacity Planning + What-If
ankavm v2.5.8 Observability

Features:
  - capture_baseline(name) — snapshot host config (sysctl, pkg hash, network, kernel)
  - check_drift(baseline_name) — diff current vs baseline
  - list_baselines()
  - whatif_add_vms(count, vcpus, ram_mb, disk_gb) — what-if capacity analysis
  - capacity_summary() — total vs allocated vs free (CPU/RAM/disk)

Persisted to /var/lib/ankavm/drift_baselines.json
"""

from __future__ import annotations
import hashlib
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("drift_capacity")

_BASELINES_FILE = Path("/var/lib/ankavm/drift_baselines.json")
_lock           = threading.Lock()


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_baselines() -> dict:
    try:
        if _BASELINES_FILE.exists():
            return json.loads(_BASELINES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("drift baselines load fail: %s", e)
    return {}


def _save_baselines(data: dict) -> None:
    try:
        _BASELINES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _BASELINES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_BASELINES_FILE)
    except Exception as e:
        log.warning("drift baselines save fail: %s", e)


# ── Config collectors ─────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _collect_sysctl() -> dict:
    """Return a dict of sysctl key→value pairs."""
    out = _run(["sysctl", "-a"])
    result: dict = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _collect_kernel() -> str:
    return _run(["uname", "-r"])


def _collect_packages_hash() -> str:
    """Hash the installed package list (dpkg or rpm)."""
    pkg_list = _run(["dpkg", "--get-selections"])
    if not pkg_list:
        pkg_list = _run(["rpm", "-qa", "--qf", "%{NAME}-%{VERSION}\n"])
    return hashlib.sha256(pkg_list.encode()).hexdigest() if pkg_list else ""


def _collect_network() -> dict:
    """Collect ip addr show summary."""
    out = _run(["ip", "-j", "addr", "show"])
    if out:
        try:
            ifaces = json.loads(out)
            return {
                iface.get("ifname", ""): {
                    "flags": iface.get("flags", []),
                    "addrs": [
                        a.get("local", "") for a in iface.get("addr_info", [])
                    ],
                }
                for iface in ifaces
            }
        except Exception:
            pass
    return {"raw": out[:2000]}


def _current_snapshot() -> dict:
    return {
        "kernel":        _collect_kernel(),
        "packages_hash": _collect_packages_hash(),
        "sysctl":        _collect_sysctl(),
        "network":       _collect_network(),
        "captured_at":   int(time.time()),
    }


# ── Host capacity helpers ─────────────────────────────────────────────────────

def _host_cpu_threads() -> int:
    """Total logical CPU threads on host."""
    out = _run(["nproc"])
    try:
        return int(out)
    except Exception:
        pass
    # fallback: /proc/cpuinfo
    try:
        count = sum(1 for line in open("/proc/cpuinfo") if line.startswith("processor"))
        return count or 1
    except Exception:
        return 1


def _host_ram_mb() -> int:
    """Total host RAM in MB from /proc/meminfo."""
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return kb // 1024
    except Exception:
        pass
    return 0


def _host_disk_gb(path: str = "/") -> float:
    """Free and total disk space in GB for path."""
    import shutil
    try:
        usage = shutil.disk_usage(path)
        return round(usage.total / (1024 ** 3), 1), round(usage.free / (1024 ** 3), 1)
    except Exception:
        return 0.0, 0.0


def _virsh_allocated() -> dict:
    """Sum vcpus and maxMemory across all defined VMs via virsh domstats."""
    out = _run(["virsh", "list", "--all"])
    vm_names = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2:
            vm_names.append(parts[1])

    total_vcpus = 0
    total_ram_mb = 0
    for name in vm_names:
        vcpu_out = _run(["virsh", "vcpucount", name, "--maximum", "--config"])
        ram_out  = _run(["virsh", "dommemstat", name])
        try:
            total_vcpus += int(vcpu_out)
        except Exception:
            pass
        # dommemstat: actual <kb> line
        for line in ram_out.splitlines():
            if line.startswith("actual"):
                try:
                    total_ram_mb += int(line.split()[1]) // 1024
                except Exception:
                    pass

    # Estimate disk from virsh domblkinfo is complex — skip, use df
    return {"vcpus": total_vcpus, "ram_mb": total_ram_mb}


# ── Public API ────────────────────────────────────────────────────────────────

def capture_baseline(name: str) -> dict:
    """Capture and persist current host config snapshot as `name`."""
    name = str(name).strip()
    if not name:
        raise ValueError("baseline name cannot be empty")
    snapshot = _current_snapshot()
    with _lock:
        baselines = _load_baselines()
        baselines[name] = snapshot
        _save_baselines(baselines)
    log.info("drift baseline captured: %s", name)
    return {"name": name, "captured_at": snapshot["captured_at"], "kernel": snapshot["kernel"]}


def list_baselines() -> list:
    """Return list of {name, captured_at, kernel} for all baselines."""
    with _lock:
        baselines = _load_baselines()
    result = []
    for name, snap in baselines.items():
        result.append({
            "name":        name,
            "captured_at": snap.get("captured_at"),
            "kernel":      snap.get("kernel", ""),
        })
    return sorted(result, key=lambda x: x.get("captured_at") or 0, reverse=True)


def check_drift(baseline_name: str) -> dict:
    """
    Compare current config to stored baseline.
    Returns {baseline, drifted_keys, added, removed, packages_changed, kernel_changed}.
    """
    with _lock:
        baselines = _load_baselines()

    if baseline_name not in baselines:
        raise KeyError(f"baseline not found: {baseline_name}")

    baseline  = baselines[baseline_name]
    current   = _current_snapshot()

    # sysctl diff
    base_sysctl = baseline.get("sysctl", {})
    curr_sysctl = current.get("sysctl", {})

    base_keys = set(base_sysctl.keys())
    curr_keys = set(curr_sysctl.keys())

    drifted_keys = [
        {"key": k, "baseline": base_sysctl[k], "current": curr_sysctl[k]}
        for k in base_keys & curr_keys
        if base_sysctl[k] != curr_sysctl[k]
    ]
    added   = sorted(curr_keys - base_keys)
    removed = sorted(base_keys - curr_keys)

    packages_changed = (
        current.get("packages_hash", "") != baseline.get("packages_hash", "")
    )
    kernel_changed = (
        current.get("kernel", "") != baseline.get("kernel", "")
    )

    return {
        "baseline":          baseline_name,
        "baseline_captured": baseline.get("captured_at"),
        "checked_at":        int(time.time()),
        "drifted_keys":      drifted_keys[:200],  # cap output
        "added":             added[:200],
        "removed":           removed[:200],
        "drift_count":       len(drifted_keys),
        "packages_changed":  packages_changed,
        "kernel_changed":    kernel_changed,
        "kernel_baseline":   baseline.get("kernel", ""),
        "kernel_current":    current.get("kernel", ""),
    }


def capacity_summary() -> dict:
    """
    Return {cpu:{total,allocated,free}, ram:{total_mb,allocated_mb,free_mb},
            disk:{total_gb,free_gb}}.
    """
    cpu_total = _host_cpu_threads()
    ram_total = _host_ram_mb()
    disk_total, disk_free = _host_disk_gb("/")

    alloc = _virsh_allocated()
    cpu_alloc = alloc.get("vcpus", 0)
    ram_alloc = alloc.get("ram_mb", 0)

    return {
        "cpu": {
            "total":     cpu_total,
            "allocated": cpu_alloc,
            "free":      max(0, cpu_total - cpu_alloc),
            "overcommit_ratio": round(cpu_alloc / cpu_total, 2) if cpu_total else None,
        },
        "ram": {
            "total_mb":     ram_total,
            "allocated_mb": ram_alloc,
            "free_mb":      max(0, ram_total - ram_alloc),
            "allocated_pct": round(ram_alloc / ram_total * 100, 1) if ram_total else None,
        },
        "disk": {
            "total_gb": disk_total,
            "free_gb":  disk_free,
            "used_gb":  round(disk_total - disk_free, 1),
            "used_pct": round((disk_total - disk_free) / disk_total * 100, 1) if disk_total else None,
        },
    }


def whatif_add_vms(
    count: int,
    vcpus: int,
    ram_mb: int,
    disk_gb: float,
) -> dict:
    """
    Simulate adding `count` VMs each with vcpus/ram_mb/disk_gb.
    Returns {fits, cpu_after_pct, ram_after_pct, disk_after_gb, overcommit_ratio,
             details}.
    """
    count   = max(1, int(count))
    vcpus   = max(1, int(vcpus))
    ram_mb  = max(1, int(ram_mb))
    disk_gb = max(0, float(disk_gb))

    summary = capacity_summary()

    cpu_total  = summary["cpu"]["total"]
    cpu_alloc  = summary["cpu"]["allocated"]
    ram_total  = summary["ram"]["total_mb"]
    ram_alloc  = summary["ram"]["allocated_mb"]
    disk_total = summary["disk"]["total_gb"]
    disk_free  = summary["disk"]["free_gb"]

    new_cpu  = cpu_alloc  + count * vcpus
    new_ram  = ram_alloc  + count * ram_mb
    new_disk = (disk_total - disk_free) + count * disk_gb

    cpu_after_pct  = round(new_cpu / cpu_total * 100, 1) if cpu_total else None
    ram_after_pct  = round(new_ram / ram_total * 100, 1) if ram_total else None
    disk_after_gb  = round(new_disk, 1)
    overcommit     = round(new_cpu / cpu_total, 2)     if cpu_total else None

    fits = (
        new_ram  <= ram_total
        and disk_after_gb <= disk_total
    )

    return {
        "fits":             fits,
        "cpu_after_pct":    cpu_after_pct,
        "ram_after_pct":    ram_after_pct,
        "disk_after_gb":    disk_after_gb,
        "disk_total_gb":    disk_total,
        "overcommit_ratio": overcommit,
        "warnings": (
            (["CPU overcommit > 4x"] if overcommit and overcommit > 4 else [])
            + (["RAM exceeds physical"] if ram_after_pct and ram_after_pct > 100 else [])
            + (["Disk exceeds capacity"] if disk_after_gb > disk_total else [])
        ),
        "request": {
            "vm_count": count,
            "vcpus_each": vcpus,
            "ram_mb_each": ram_mb,
            "disk_gb_each": disk_gb,
        },
    }






