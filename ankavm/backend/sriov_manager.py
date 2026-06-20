"""
SR-IOV Manager — PF discovery, VF creation, VM assignment via libvirt hostdev.
"""
import os
import re
import subprocess
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("sriov_manager")

NET_DIR = Path("/sys/class/net")


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def _read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return default


def list_pf_devices() -> list:
    """Enumerate SR-IOV capable physical NICs."""
    out = []
    try:
        if not NET_DIR.exists():
            return []
        for nic in NET_DIR.iterdir():
            tot = nic / "device" / "sriov_totalvfs"
            if not tot.exists():
                continue
            try:
                total = int(_read(tot, "0"))
            except ValueError:
                total = 0
            if total <= 0:
                continue
            num = int(_read(nic / "device" / "sriov_numvfs", "0") or 0)
            pci = ""
            try:
                pci = os.path.basename(os.readlink(nic / "device"))
            except Exception:
                pass
            out.append({
                "pf_name": nic.name,
                "pci_addr": pci,
                "totalvfs": total,
                "numvfs": num,
                "driver": os.path.basename(os.readlink(nic / "device" / "driver"))
                          if (nic / "device" / "driver").exists() else "",
                "link": _read(nic / "operstate", "unknown"),
            })
    except Exception as e:
        log.error("list_pf_devices: %s", e)
    return out


def create_vfs(pf_name: str, num_vfs: int) -> dict:
    try:
        path = NET_DIR / pf_name / "device" / "sriov_numvfs"
        if not path.exists():
            return {"ok": False, "error": f"{pf_name} not SR-IOV capable"}
        # Reset to 0 first (kernel requirement)
        try:
            path.write_text("0")
        except Exception:
            pass
        path.write_text(str(int(num_vfs)))
        return {"ok": True, "pf": pf_name, "numvfs": int(num_vfs)}
    except Exception as e:
        log.error("create_vfs %s: %s", pf_name, e)
        return {"ok": False, "error": str(e)}


def list_vfs(pf_name: str) -> list:
    """Iterate virtfn* symlinks under the PF device."""
    out = []
    try:
        dev_dir = NET_DIR / pf_name / "device"
        if not dev_dir.exists():
            return []
        for entry in sorted(dev_dir.iterdir()):
            if not entry.name.startswith("virtfn"):
                continue
            try:
                vf_pci = os.path.basename(os.readlink(entry))
            except Exception:
                continue
            idx = int(re.sub(r"\D", "", entry.name) or 0)
            vf_info = {"index": idx, "pci_addr": vf_pci}
            # mac / vlan via ip link if available
            try:
                r = subprocess.run(["ip", "link", "show", pf_name],
                                   capture_output=True, text=True, timeout=5)
                for line in r.stdout.splitlines():
                    m = re.match(rf"\s*vf\s+{idx}\s+(.*)", line)
                    if m:
                        rest = m.group(1)
                        mm = re.search(r"MAC ([0-9a-f:]+)", rest)
                        vl = re.search(r"vlan\s+(\d+)", rest)
                        ls = re.search(r"link-state\s+(\S+)", rest)
                        if mm:
                            vf_info["mac"] = mm.group(1)
                        if vl:
                            vf_info["vlan"] = int(vl.group(1))
                        if ls:
                            vf_info["link_state"] = ls.group(1).rstrip(",")
                        break
            except Exception:
                pass
            out.append(vf_info)
    except Exception as e:
        log.error("list_vfs %s: %s", pf_name, e)
    return out


def _pci_parts(addr: str):
    # 0000:01:00.1
    m = re.match(r"(?:([0-9a-f]+):)?([0-9a-f]+):([0-9a-f]+)\.([0-9a-f]+)", addr.lower())
    if not m:
        raise ValueError(f"invalid PCI: {addr}")
    dom = m.group(1) or "0000"
    return dom, m.group(2), m.group(3), m.group(4)


def assign_vf_to_vm(vm_id: str, vf_pci_addr: str) -> dict:
    try:
        dom_str, bus, slot, fn = _pci_parts(vf_pci_addr)
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            devices = root.find("devices")
            if devices is None:
                devices = ET.SubElement(root, "devices")
            hd = ET.SubElement(devices, "hostdev")
            hd.set("mode", "subsystem")
            hd.set("type", "pci")
            hd.set("managed", "yes")
            src = ET.SubElement(hd, "source")
            addr = ET.SubElement(src, "address")
            addr.set("domain", "0x" + dom_str)
            addr.set("bus", "0x" + bus)
            addr.set("slot", "0x" + slot)
            addr.set("function", "0x" + fn)
            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "vm_id": vm_id, "vf_pci": vf_pci_addr,
                    "note": "VM restart required"}
        finally:
            conn.close()
    except Exception as e:
        log.error("assign_vf_to_vm: %s", e)
        return {"ok": False, "error": str(e)}






