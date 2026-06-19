"""
vTPM Manager â€” Libvirt TPM passthrough + emulated (swtpm) support.
"""
import subprocess
import logging
import xml.etree.ElementTree as ET
try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("vtpm_manager")

def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)

def list_vm_tpm(vm_id: str) -> dict:
    """Return current TPM config for a VM."""
    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        root = ET.fromstring(dom.XMLDesc(0))
        tpm = root.find(".//tpm")
        if tpm is None:
            return {"has_tpm": False}
        return {
            "has_tpm": True,
            "model": tpm.get("model", "tpm-tis"),
            "backend": tpm.find("backend").get("type") if tpm.find("backend") is not None else "unknown",
            "version": tpm.find("backend").get("version", "2.0") if tpm.find("backend") is not None else "2.0",
        }
    finally:
        conn.close()

def add_vtpm(vm_id: str, model: str = "tpm-tis", version: str = "2.0") -> dict:
    """Add emulated vTPM to VM. Requires swtpm installed on host."""
    # Check swtpm available
    r = subprocess.run(["which", "swtpm"], capture_output=True)
    if r.returncode != 0:
        return {"ok": False, "error": "swtpm not installed. Run: apt install swtpm swtpm-tools"}

    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        was_active = dom.isActive()
        root = ET.fromstring(dom.XMLDesc(0))

        # Remove existing TPM if any
        devices = root.find("devices")
        for tpm in devices.findall("tpm"):
            devices.remove(tpm)

        # Add emulated TPM
        tpm_el = ET.SubElement(devices, "tpm")
        tpm_el.set("model", model)
        backend = ET.SubElement(tpm_el, "backend")
        backend.set("type", "emulator")
        backend.set("version", version)

        conn.defineXML(ET.tostring(root, encoding="unicode"))
        return {"ok": True, "model": model, "version": version, "backend": "emulator",
                "note": "VM restart required for TPM to activate"}
    finally:
        conn.close()

def remove_vtpm(vm_id: str) -> dict:
    """Remove vTPM from VM."""
    conn = _connect()
    try:
        dom = conn.lookupByName(vm_id)
        root = ET.fromstring(dom.XMLDesc(0))
        devices = root.find("devices")
        removed = 0
        for tpm in devices.findall("tpm"):
            devices.remove(tpm)
            removed += 1
        conn.defineXML(ET.tostring(root, encoding="unicode"))
        return {"ok": True, "removed": removed}
    finally:
        conn.close()

def check_swtpm() -> dict:
    """Check if swtpm is available on host."""
    r = subprocess.run(["which", "swtpm"], capture_output=True, text=True)
    r2 = subprocess.run(["swtpm", "--version"], capture_output=True, text=True)
    return {
        "available": r.returncode == 0,
        "path": r.stdout.strip(),
        "version": r2.stdout.strip().split("\n")[0] if r2.returncode == 0 else None,
    }


# â”€â”€ v2.5.4 spec API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def enable_vtpm(vm_id: str, version: str = "2.0") -> dict:
    """Add tpm-crb emulator (TPM 2.0) â€” Win11/BitLocker friendly."""
    try:
        return add_vtpm(vm_id, model="tpm-crb", version=version)
    except Exception as e:
        log.error("enable_vtpm: %s", e)
        return {"ok": False, "error": str(e)}


def disable_vtpm(vm_id: str) -> dict:
    try:
        return remove_vtpm(vm_id)
    except Exception as e:
        log.error("disable_vtpm: %s", e)
        return {"ok": False, "error": str(e)}


def vtpm_status(vm_id: str) -> dict:
    try:
        info = list_vm_tpm(vm_id)
        return {
            "enabled": bool(info.get("has_tpm")),
            "version": info.get("version", "2.0"),
            "model": info.get("model"),
            "backend": info.get("backend"),
        }
    except Exception as e:
        log.error("vtpm_status: %s", e)
        return {"enabled": False, "version": "2.0", "error": str(e)}


def list_vtpm_vms() -> list:
    """List VMs that have vTPM enabled."""
    if libvirt is None:
        return []
    try:
        conn = _connect()
        try:
            out = []
            for dom in conn.listAllDomains():
                try:
                    root = ET.fromstring(dom.XMLDesc(0))
                    if root.find(".//tpm") is not None:
                        out.append({"vm_id": dom.name(), "uuid": dom.UUIDString()})
                except Exception:
                    continue
            return out
        finally:
            conn.close()
    except Exception as e:
        log.error("list_vtpm_vms: %s", e)
        return []







