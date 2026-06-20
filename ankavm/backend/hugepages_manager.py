"""
HugePages Manager — host-level config + per-VM libvirt memoryBacking.
"""
import os
import subprocess
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("hugepages_manager")

MEMINFO = "/proc/meminfo"
THP_PATH = "/sys/kernel/mm/transparent_hugepage/enabled"
HP_2MB_NR = "/sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages"
HP_2MB_FREE = "/sys/kernel/mm/hugepages/hugepages-2048kB/free_hugepages"
HP_1GB_NR = "/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages"
HP_1GB_FREE = "/sys/kernel/mm/hugepages/hugepages-1048576kB/free_hugepages"


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def _read_int(path, default=0):
    try:
        return int(Path(path).read_text().strip())
    except Exception:
        return default


def _parse_meminfo():
    out = {}
    try:
        for line in Path(MEMINFO).read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    except Exception as e:
        log.warning("meminfo: %s", e)
    return out


def get_status() -> dict:
    try:
        mi = _parse_meminfo()
        thp = "unknown"
        try:
            txt = Path(THP_PATH).read_text().strip()
            # format: "always [madvise] never" — bracketed is active
            for token in txt.split():
                if token.startswith("["):
                    thp = token.strip("[]")
                    break
        except Exception:
            pass
        hpsize_kb = 2048
        try:
            hpsize_kb = int(mi.get("Hugepagesize", "2048 kB").split()[0])
        except Exception:
            pass
        return {
            "nr_hugepages": _read_int(HP_2MB_NR),
            "free_hugepages": _read_int(HP_2MB_FREE),
            "nr_hugepages_1gb": _read_int(HP_1GB_NR),
            "free_hugepages_1gb": _read_int(HP_1GB_FREE),
            "hugepagesize_kb": hpsize_kb,
            "transparent_enabled": thp,
            "meminfo_HugePages_Total": mi.get("HugePages_Total"),
            "meminfo_HugePages_Free": mi.get("HugePages_Free"),
        }
    except Exception as e:
        log.error("get_status: %s", e)
        return {"nr_hugepages": 0, "free_hugepages": 0,
                "hugepagesize_kb": 2048, "transparent_enabled": "unknown",
                "error": str(e)}


def configure(pages_2mb: int = 0, pages_1gb: int = 0) -> dict:
    """Apply at runtime via sysctl (does not survive reboot unless grub edited)."""
    try:
        applied = {}
        if pages_2mb is not None:
            r = subprocess.run(
                ["sysctl", "-w", f"vm.nr_hugepages={int(pages_2mb)}"],
                capture_output=True, text=True, timeout=10
            )
            applied["2mb"] = {"rc": r.returncode, "stderr": r.stderr.strip()[:200]}
        if pages_1gb and int(pages_1gb) > 0:
            # 1GB pages must be set per-node typically; try write directly
            try:
                Path(HP_1GB_NR).write_text(str(int(pages_1gb)))
                applied["1gb"] = {"rc": 0}
            except Exception as e:
                applied["1gb"] = {"rc": -1, "stderr": str(e)}
        return {"ok": True, "applied": applied, "status": get_status()}
    except Exception as e:
        log.error("configure: %s", e)
        return {"ok": False, "error": str(e)}


def apply_to_vm(vm_id: str, hugepage_size: str = "2M") -> dict:
    """Add <memoryBacking><hugepages><page size=.../></hugepages></memoryBacking>."""
    try:
        size_kib = 1048576 if hugepage_size.upper() in ("1G", "1GB") else 2048
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            for mb in root.findall("memoryBacking"):
                root.remove(mb)
            mb = ET.SubElement(root, "memoryBacking")
            hp = ET.SubElement(mb, "hugepages")
            page = ET.SubElement(hp, "page")
            page.set("size", str(size_kib))
            page.set("unit", "KiB")
            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "page_size_kib": size_kib,
                    "note": "VM restart required"}
        finally:
            conn.close()
    except Exception as e:
        log.error("apply_to_vm: %s", e)
        return {"ok": False, "error": str(e)}


def remove_from_vm(vm_id: str) -> dict:
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            removed = 0
            for mb in list(root.findall("memoryBacking")):
                root.remove(mb)
                removed += 1
            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "removed": removed}
        finally:
            conn.close()
    except Exception as e:
        log.error("remove_from_vm: %s", e)
        return {"ok": False, "error": str(e)}






