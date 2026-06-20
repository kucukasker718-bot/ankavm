"""
ankavm Confidential VM — AMD SEV / Intel TDX
─────────────────────────────────────────────
Memory-encrypted confidential VMs.
- AMD SEV (Secure Encrypted Virtualization) — qemu launch-security type='sev'
- AMD SEV-SNP (Secure Nested Paging) — sev-snp
- Intel TDX (Trust Domain Extensions) — tdx
- Detection via /sys/module/kvm_amd/parameters/sev + cpuid

Persists policy at /var/lib/ankavm/confidential_vm.json
"""
from __future__ import annotations
import os, json, logging, subprocess
from pathlib import Path

log = logging.getLogger("confidential_vm")
_CFG = Path("/var/lib/ankavm/confidential_vm.json")


def detect_support() -> dict:
    """Detect host CPU + kernel support."""
    out = {"sev": False, "sev_es": False, "sev_snp": False, "tdx": False, "details": {}}
    try:
        for name, path in [
            ("sev",      "/sys/module/kvm_amd/parameters/sev"),
            ("sev_es",   "/sys/module/kvm_amd/parameters/sev_es"),
            ("sev_snp",  "/sys/module/kvm_amd/parameters/sev_snp"),
            ("tdx",      "/sys/module/kvm_intel/parameters/tdx"),
        ]:
            try:
                v = Path(path).read_text().strip()
                out[name] = v in ("Y", "1", "y", "true")
                out["details"][name] = v
            except Exception:
                pass
    except Exception as e:
        log.warning("detect_support: %s", e)
    # CPUID quick check — direct read (no subprocess) — SEC-028
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").lower()
        if "sev" in cpuinfo: out["details"]["cpu_sev_flag"] = True
        if "tdx" in cpuinfo: out["details"]["cpu_tdx_flag"] = True
    except Exception:
        pass
    return out


def _load() -> dict:
    try:
        if _CFG.exists():
            return json.loads(_CFG.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"vms": {}}


def _save(d: dict):
    _CFG.parent.mkdir(parents=True, exist_ok=True)
    _CFG.write_text(json.dumps(d, indent=2), encoding="utf-8")


def list_protected_vms() -> list:
    return [{"vm_id": k, **v} for k, v in _load().get("vms", {}).items()]


def enable_for_vm(vm_id: str, mode: str = "sev") -> dict:
    """Mark VM as confidential — actual libvirt XML injection
    must be performed at VM creation/edit time by vm_manager."""
    if mode not in ("sev", "sev-es", "sev-snp", "tdx"):
        return {"ok": False, "error": f"unsupported mode: {mode}"}
    d = _load()
    d.setdefault("vms", {})[vm_id] = {"mode": mode, "enabled": True}
    _save(d)
    log.info("confidential_vm enabled: %s (%s)", vm_id, mode)
    return {"ok": True, "vm_id": vm_id, "mode": mode}


def disable_for_vm(vm_id: str) -> dict:
    d = _load()
    if vm_id in d.get("vms", {}):
        del d["vms"][vm_id]
        _save(d)
    return {"ok": True, "vm_id": vm_id}


def get_vm_config(vm_id: str) -> dict:
    return _load().get("vms", {}).get(vm_id, {"enabled": False})


def generate_libvirt_xml_snippet(mode: str, policy_hex: str = "0x0001") -> str:
    """Return XML to inject into <launchSecurity> for libvirt."""
    if mode == "tdx":
        return '<launchSecurity type="tdx"/>'
    # SEV / SEV-ES / SEV-SNP
    return (f'<launchSecurity type="sev">\n'
            f'  <policy>{policy_hex}</policy>\n'
            f'  <cbitpos>47</cbitpos>\n'
            f'  <reducedPhysBits>1</reducedPhysBits>\n'
            f'</launchSecurity>')


def generate_vtpm_xml_snippet(persistent_dir: str = "/var/lib/ankavm/vtpm") -> str:
    """vTPM 2.0 device snippet for libvirt <devices>."""
    return ('<tpm model="tpm-crb">\n'
            '  <backend type="emulator" version="2.0"/>\n'
            '</tpm>')


def generate_secure_boot_xml(loader_path: str = "/usr/share/OVMF/OVMF_CODE.secboot.fd",
                             nvram_template: str = "/usr/share/OVMF/OVMF_VARS.secboot.fd") -> str:
    """UEFI Secure Boot OVMF loader snippet for libvirt <os>."""
    return (f'<loader readonly="yes" secure="yes" type="pflash">{loader_path}</loader>\n'
            f'<nvram template="{nvram_template}"/>\n'
            f'<smm state="on"/>')


def set_secure_boot(vm_id: str, enabled: bool) -> dict:
    d = _load()
    rec = d.setdefault("vms", {}).setdefault(vm_id, {})
    rec["secure_boot"] = bool(enabled)
    _save(d)
    return {"ok": True, "vm_id": vm_id, "secure_boot": rec["secure_boot"]}


def set_vtpm(vm_id: str, enabled: bool) -> dict:
    d = _load()
    rec = d.setdefault("vms", {}).setdefault(vm_id, {})
    rec["vtpm"] = bool(enabled)
    _save(d)
    return {"ok": True, "vm_id": vm_id, "vtpm": rec["vtpm"]}


def capture_attestation(vm_id: str) -> dict:
    """Capture a launch-measurement attestation report for an SEV/SNP/TDX VM.

    On SEV(-SNP): runs `virsh domlaunchsecinfo <vm>` and parses the measurement.
    On TDX: extracts the TDREPORT from QGS (Quote Generation Service) if available.
    On systems where the tooling is missing, returns a stub record so callers
    can still track the attestation request in the audit log.
    """
    cfg = get_vm_config(vm_id)
    mode = cfg.get("mode")
    out = {"vm_id": vm_id, "mode": mode, "ts": __import__("time").time(),
           "measurement": None, "policy": None, "raw": None, "ok": False}
    if not mode:
        out["error"] = "vm is not marked confidential"
        return out
    try:
        if mode in ("sev", "sev-es", "sev-snp"):
            r = subprocess.run(["virsh", "domlaunchsecinfo", vm_id],
                               capture_output=True, text=True, timeout=8)
            out["raw"] = r.stdout
            for line in r.stdout.splitlines():
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip()
                if k.endswith("measurement"):
                    out["measurement"] = v
                elif k.endswith("policy"):
                    out["policy"] = v
            out["ok"] = bool(out["measurement"])
        elif mode == "tdx":
            qgs = "/var/run/tdx-qgs/qgs.socket"
            out["raw"] = f"qgs={qgs} (TDREPORT extraction requires sgx-dcap tooling)"
            out["ok"] = False
            out["error"] = "tdx attestation requires sgx-dcap qgs running"
    except Exception as e:
        log.warning("capture_attestation %s: %s", vm_id, e)
        out["error"] = str(e)
    # persist last attestation
    d = _load()
    rec = d.setdefault("vms", {}).setdefault(vm_id, {})
    rec["last_attestation"] = {k: v for k, v in out.items() if k != "raw"}
    _save(d)
    return out


def get_attestation(vm_id: str) -> dict:
    rec = _load().get("vms", {}).get(vm_id, {})
    return rec.get("last_attestation", {"ok": False, "error": "no attestation yet"})






