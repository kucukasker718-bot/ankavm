"""
NUMA Manager â€” Custom NUMA topology for KVM/libvirt VMs.
"""
import xml.etree.ElementTree as ET
import libvirt

def _connect():
    import config
    return libvirt.open(config.LIBVIRT_URI)

def get_host_numa() -> dict:
    """Get host NUMA topology."""
    import subprocess
    r = subprocess.run(["numactl", "--hardware"], capture_output=True, text=True)
    r2 = subprocess.run(["lscpu"], capture_output=True, text=True)
    nodes = []
    try:
        for line in r.stdout.splitlines():
            if line.startswith("node") and "cpus:" in line:
                parts = line.split()
                node_id = int(parts[1])
                cpus = [int(c) for c in parts[3:] if c.isdigit()]
                nodes.append({"node": node_id, "cpus": cpus})
    except Exception:
        pass
    return {"nodes": nodes, "raw": r.stdout, "lscpu": r2.stdout[:2000]}

def get_vm_numa(vm_id: str) -> dict:
    """Get current NUMA config for a VM."""
    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        root = ET.fromstring(dom.XMLDesc(0))
        cpu_el = root.find("cpu")
        numa_el = root.find(".//numa")
        cells = []
        if numa_el is not None:
            for cell in numa_el.findall("cell"):
                cells.append({
                    "id": cell.get("id"),
                    "cpus": cell.get("cpus"),
                    "memory": cell.get("memory"),
                    "unit": cell.get("unit", "KiB"),
                })
        return {"has_numa": len(cells) > 0, "cells": cells}
    finally:
        conn.close()

def set_vm_numa(vm_id: str, cells: list) -> dict:
    """
    Set NUMA topology for VM.
    cells: [{"id": 0, "cpus": "0-3", "memory": 2097152}, ...]  # memory in KiB
    VM must be stopped.
    """
    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        if dom.isActive():
            return {"ok": False, "error": "VM must be stopped to change NUMA topology"}

        root = ET.fromstring(dom.XMLDesc(0))
        cpu_el = root.find("cpu")
        if cpu_el is None:
            cpu_el = ET.SubElement(root, "cpu")

        # Remove existing numa
        for numa in cpu_el.findall("numa"):
            cpu_el.remove(numa)

        numa_el = ET.SubElement(cpu_el, "numa")
        for cell in cells:
            cell_el = ET.SubElement(numa_el, "cell")
            cell_el.set("id", str(cell.get("id", 0)))
            cell_el.set("cpus", str(cell.get("cpus", "0")))
            cell_el.set("memory", str(cell.get("memory", 1048576)))
            cell_el.set("unit", cell.get("unit", "KiB"))

        conn.defineXML(ET.tostring(root, encoding="unicode"))
        return {"ok": True, "cells": cells}
    finally:
        conn.close()

def remove_vm_numa(vm_id: str) -> dict:
    """Remove NUMA topology from VM."""
    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        root = ET.fromstring(dom.XMLDesc(0))
        cpu_el = root.find("cpu")
        if cpu_el is not None:
            for numa in cpu_el.findall("numa"):
                cpu_el.remove(numa)
        conn.defineXML(ET.tostring(root, encoding="unicode"))
        return {"ok": True}
    finally:
        conn.close()






