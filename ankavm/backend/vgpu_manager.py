"""
vGPU Manager — NVIDIA GRID / MIG mdev discovery + assignment.
"""
import os
import uuid as _uuid
import subprocess
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("vgpu_manager")

MDEV_BUS = Path("/sys/class/mdev_bus")


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def _read(p, default=""):
    try:
        return Path(p).read_text().strip()
    except Exception:
        return default


def detect_gpu() -> list:
    out = []
    # NVIDIA
    try:
        r = subprocess.run(["nvidia-smi", "-L"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if line:
                    out.append({"vendor": "nvidia", "info": line})
    except Exception:
        pass
    # AMD / others via lspci
    try:
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if "VGA" in line or "3D controller" in line:
                    vendor = "amd" if "AMD" in line or "ATI" in line else (
                             "intel" if "Intel" in line else (
                             "nvidia" if "NVIDIA" in line else "other"))
                    out.append({"vendor": vendor, "pci_line": line.strip()})
    except Exception:
        pass
    return out


def list_mdev_types() -> list:
    """Walk /sys/class/mdev_bus/<pci>/mdev_supported_types/<type>."""
    out = []
    try:
        if not MDEV_BUS.exists():
            return []
        for pci in MDEV_BUS.iterdir():
            t_root = pci / "mdev_supported_types"
            if not t_root.exists():
                continue
            for t in t_root.iterdir():
                out.append({
                    "parent_pci": pci.name,
                    "type": t.name,
                    "name": _read(t / "name"),
                    "description": _read(t / "description"),
                    "available_instances": _read(t / "available_instances", "0"),
                })
    except Exception as e:
        log.error("list_mdev_types: %s", e)
    return out


def create_mdev(parent_pci: str, mdev_type: str, uuid: str = None) -> dict:
    try:
        if not uuid:
            uuid = str(_uuid.uuid4())
        create_path = MDEV_BUS / parent_pci / "mdev_supported_types" / mdev_type / "create"
        if not create_path.parent.exists():
            return {"ok": False, "error": f"type {mdev_type} not found on {parent_pci}"}
        create_path.write_text(uuid)
        return {"ok": True, "uuid": uuid, "parent_pci": parent_pci, "type": mdev_type}
    except Exception as e:
        log.error("create_mdev: %s", e)
        return {"ok": False, "error": str(e)}


def assign_mdev_to_vm(vm_id: str, mdev_uuid: str) -> dict:
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            devices = root.find("devices")
            if devices is None:
                devices = ET.SubElement(root, "devices")
            hd = ET.SubElement(devices, "hostdev")
            hd.set("mode", "subsystem")
            hd.set("type", "mdev")
            hd.set("model", "vfio-pci")
            hd.set("display", "off")
            src = ET.SubElement(hd, "source")
            addr = ET.SubElement(src, "address")
            addr.set("uuid", mdev_uuid)
            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "vm_id": vm_id, "mdev_uuid": mdev_uuid,
                    "note": "VM restart required"}
        finally:
            conn.close()
    except Exception as e:
        log.error("assign_mdev_to_vm: %s", e)
        return {"ok": False, "error": str(e)}


def list_active_mdevs() -> list:
    out = []
    try:
        if not MDEV_BUS.exists():
            return []
        for pci in MDEV_BUS.iterdir():
            for child in pci.iterdir():
                # Active mdevs appear as UUID-named directories
                if len(child.name) == 36 and child.name.count("-") == 4:
                    out.append({
                        "uuid": child.name,
                        "parent_pci": pci.name,
                        "type": os.path.basename(os.readlink(child / "mdev_type"))
                                 if (child / "mdev_type").exists() else "",
                    })
    except Exception as e:
        log.error("list_active_mdevs: %s", e)
    return out


def remove_mdev(mdev_uuid: str) -> dict:
    try:
        if not MDEV_BUS.exists():
            return {"ok": False, "error": "mdev_bus not available"}
        for pci in MDEV_BUS.iterdir():
            target = pci / mdev_uuid / "remove"
            if target.exists():
                target.write_text("1")
                return {"ok": True, "uuid": mdev_uuid}
        return {"ok": False, "error": "uuid not found"}
    except Exception as e:
        log.error("remove_mdev: %s", e)
        return {"ok": False, "error": str(e)}






