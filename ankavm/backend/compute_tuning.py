"""
ankavm Compute Tuning — HugePages, KSM, NUMA, PCIe Pool
─────────────────────────────────────────────────────────
Düşük seviye performans tunings.

API: configure_*, get_*_status
"""

import subprocess, json, logging
from pathlib import Path

log = logging.getLogger("compute_tuning")


# ── HugePages ────────────────────────────────────────────────────────────────
def hugepages_status() -> dict:
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "HugePages_Total:" in line:
                    info["total"] = int(line.split()[1])
                elif "HugePages_Free:" in line:
                    info["free"] = int(line.split()[1])
                elif "HugePages_Rsvd:" in line:
                    info["reserved"] = int(line.split()[1])
                elif "Hugepagesize:" in line:
                    info["size_kb"] = int(line.split()[1])
    except Exception as e:
        return {"error": str(e)}
    info["total_mb"] = info.get("total", 0) * info.get("size_kb", 0) // 1024
    info["enabled"] = info.get("total", 0) > 0
    return info


def hugepages_configure(count: int) -> dict:
    """Sysctl ile hugepage sayısı ayarla."""
    try:
        r = subprocess.run(["sysctl", "-w", f"vm.nr_hugepages={count}"],
                           capture_output=True, text=True, timeout=10)
        # Persist
        Path("/etc/sysctl.d/99-ankavm-hugepages.conf").write_text(
            f"vm.nr_hugepages = {count}\n"
        )
        return {"ok": r.returncode == 0, "count": count,
                "stdout": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── KSM (Kernel Same-page Merging) ──────────────────────────────────────────
def ksm_status() -> dict:
    out = {}
    base = Path("/sys/kernel/mm/ksm")
    if not base.exists():
        return {"available": False}
    for key in ["run", "pages_sharing", "pages_shared", "pages_to_scan",
                "sleep_millisecs", "merge_across_nodes"]:
        try:
            out[key] = int((base / key).read_text().strip())
        except Exception:
            pass
    out["available"] = True
    out["enabled"]   = out.get("run", 0) == 1
    # Tasarruf hesabı
    try:
        page_size = 4096
        out["saved_mb"] = (out.get("pages_sharing", 0) * page_size) // (1024 * 1024)
    except Exception:
        out["saved_mb"] = 0
    return out


def ksm_configure(enabled: bool, pages_to_scan: int = 100,
                   sleep_ms: int = 200) -> dict:
    base = Path("/sys/kernel/mm/ksm")
    if not base.exists():
        return {"ok": False, "error": "KSM mevcut değil"}
    try:
        (base / "run").write_text("1" if enabled else "0")
        if enabled:
            (base / "pages_to_scan").write_text(str(pages_to_scan))
            (base / "sleep_millisecs").write_text(str(sleep_ms))
        # systemd: ksmtuned varsa yönet
        if enabled:
            subprocess.run(["systemctl", "enable", "--now", "ksmtuned"],
                           capture_output=True, timeout=10)
        return {"ok": True, "enabled": enabled,
                "pages_to_scan": pages_to_scan, "sleep_ms": sleep_ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── NUMA ────────────────────────────────────────────────────────────────────
def numa_topology() -> dict:
    try:
        r = subprocess.run(["numactl", "--hardware"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return {"available": True, "output": r.stdout}
    except FileNotFoundError:
        return {"available": False, "error": "numactl yok"}
    except Exception as e:
        return {"available": False, "error": str(e)}
    return {"available": False}


def numa_set_vm_pin(vm_id: str, numa_node: int) -> dict:
    """VM'i belirli NUMA node'una pinle."""
    try:
        r = subprocess.run(
            ["virsh", "numatune", vm_id, "--mode", "strict", "--nodeset", str(numa_node), "--live", "--config"],
            capture_output=True, text=True, timeout=10
        )
        return {"ok": r.returncode == 0, "vm": vm_id, "node": numa_node,
                "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── PCIe Device Pool ────────────────────────────────────────────────────────
def list_pcie_devices() -> list:
    """lspci -mm parse → tüm PCIe device list."""
    out = []
    try:
        r = subprocess.run(["lspci", "-mm", "-nn"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            parts = [p.strip('"') for p in line.split(' ', 4)]
            if len(parts) >= 4:
                out.append({
                    "address":  parts[0],
                    "class":    parts[1],
                    "vendor":   parts[2] if len(parts) > 2 else "",
                    "device":   parts[3] if len(parts) > 3 else "",
                    "extra":    parts[4] if len(parts) > 4 else "",
                })
    except Exception as e:
        log.warning("lspci hatası: %s", e)
    return out


def list_iommu_groups() -> dict:
    """IOMMU group'ları döndür — VFIO passthrough için."""
    groups = {}
    base = Path("/sys/kernel/iommu_groups")
    if not base.exists():
        return {"available": False}
    try:
        for grp_dir in base.iterdir():
            if grp_dir.is_dir():
                grp = grp_dir.name
                devices = []
                dev_dir = grp_dir / "devices"
                if dev_dir.exists():
                    for dev in dev_dir.iterdir():
                        devices.append(dev.name)
                groups[grp] = devices
    except Exception as e:
        log.warning("IOMMU: %s", e)
    return {"available": True, "groups": groups, "count": len(groups)}






