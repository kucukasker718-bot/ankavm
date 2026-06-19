"""
SecureBoot Manager â€” UEFI Secure Boot enforcement for libvirt VMs.

Uses OVMF_CODE.secboot.fd + OVMF_VARS.secboot.fd and enables SMM, which is
required for Secure Boot variable protection.
"""
import os
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("secureboot_manager")

OVMF_CODE_SECBOOT_CANDIDATES = [
    "/usr/share/OVMF/OVMF_CODE.secboot.fd",
    "/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd",
    "/usr/share/edk2-ovmf/OVMF_CODE.secboot.fd",
    "/usr/share/qemu/OVMF_CODE.secboot.fd",
]
OVMF_VARS_SECBOOT_CANDIDATES = [
    "/usr/share/OVMF/OVMF_VARS.secboot.fd",
    "/usr/share/OVMF/OVMF_VARS.fd",
    "/usr/share/edk2/ovmf/OVMF_VARS.secboot.fd",
    "/usr/share/edk2-ovmf/OVMF_VARS.secboot.fd",
]
VARS_DIR = Path("/var/lib/libvirt/qemu/nvram")


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def _find(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def enable_secureboot(vm_id: str) -> dict:
    """Switch firmware to OVMF secboot + smm=on. VM must be off."""
    try:
        code = _find(OVMF_CODE_SECBOOT_CANDIDATES)
        if not code:
            return {"ok": False, "error": "OVMF_CODE.secboot.fd not found â€” install ovmf/edk2-ovmf"}
        vars_template = _find(OVMF_VARS_SECBOOT_CANDIDATES)
        if not vars_template:
            return {"ok": False, "error": "OVMF_VARS template not found"}

        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            os_el = root.find("os")
            if os_el is None:
                return {"ok": False, "error": "VM has no <os> element"}

            # type arch hint
            type_el = os_el.find("type")
            if type_el is not None:
                type_el.set("arch", type_el.get("arch", "x86_64"))
                type_el.set("machine", type_el.get("machine") or "q35")

            # loader
            for el in list(os_el.findall("loader")) + list(os_el.findall("nvram")):
                os_el.remove(el)
            loader = ET.SubElement(os_el, "loader")
            loader.set("readonly", "yes")
            loader.set("type", "pflash")
            loader.set("secure", "yes")
            loader.text = code

            try:
                VARS_DIR.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            nvram_path = str(VARS_DIR / f"{vm_id}_VARS.secboot.fd")
            nvram = ET.SubElement(os_el, "nvram")
            nvram.set("template", vars_template)
            nvram.text = nvram_path

            # SMM
            features = root.find("features")
            if features is None:
                features = ET.SubElement(root, "features")
            for smm in features.findall("smm"):
                features.remove(smm)
            smm = ET.SubElement(features, "smm")
            smm.set("state", "on")

            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "firmware": "OVMF", "secure": True,
                    "loader": code, "nvram": nvram_path,
                    "note": "VM restart required."}
        finally:
            conn.close()
    except Exception as e:
        log.error("enable_secureboot: %s", e)
        return {"ok": False, "error": str(e)}


def disable_secureboot(vm_id: str) -> dict:
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            os_el = root.find("os")
            removed = 0
            if os_el is not None:
                for el in list(os_el.findall("loader")) + list(os_el.findall("nvram")):
                    os_el.remove(el)
                    removed += 1
            features = root.find("features")
            if features is not None:
                for smm in features.findall("smm"):
                    features.remove(smm)
                    removed += 1
            conn.defineXML(ET.tostring(root, encoding="unicode"))
            return {"ok": True, "removed": removed}
        finally:
            conn.close()
    except Exception as e:
        log.error("disable_secureboot: %s", e)
        return {"ok": False, "error": str(e)}


def secureboot_status(vm_id: str) -> dict:
    try:
        conn = _connect()
        try:
            dom = conn.lookupByName(vm_id)
            root = ET.fromstring(dom.XMLDesc(0))
            loader = root.find("./os/loader")
            smm = root.find("./features/smm")
            enabled = (loader is not None and loader.get("secure") == "yes"
                       and smm is not None and smm.get("state") == "on")
            return {
                "enabled": bool(enabled),
                "firmware": "OVMF" if loader is not None else "BIOS",
                "loader": loader.text if loader is not None else None,
                "smm": smm.get("state") if smm is not None else "off",
            }
        finally:
            conn.close()
    except Exception as e:
        log.error("secureboot_status: %s", e)
        return {"enabled": False, "firmware": "unknown", "error": str(e)}


def list_secureboot_vms() -> list:
    if libvirt is None:
        return []
    try:
        conn = _connect()
        try:
            out = []
            for dom in conn.listAllDomains():
                try:
                    root = ET.fromstring(dom.XMLDesc(0))
                    loader = root.find("./os/loader")
                    if loader is not None and loader.get("secure") == "yes":
                        out.append({"vm_id": dom.name()})
                except Exception:
                    continue
            return out
        finally:
            conn.close()
    except Exception as e:
        log.error("list_secureboot_vms: %s", e)
        return []






