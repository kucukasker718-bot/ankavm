"""
kubevirt_integration.py — KubeVirt Integration for ankavm
ankavm v2.5.10 Cloud/K8s

Features:
  - detect_kubevirt() — check kubectl get kubevirt in any namespace
  - import_from_kubevirt(vmi_name) — import a KubeVirt VMI as ankavm VM
  - export_to_kubevirt(vm_id) — generate KubeVirt VirtualMachine YAML for an ankavm VM
  - list_kubevirt_vms() — list KubeVirt VMIs via kubectl

Config persisted to /var/lib/ankavm/kubevirt.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("kubevirt_integration")

_STATE_FILE = Path("/var/lib/ankavm/kubevirt.json")
_lock       = threading.Lock()

_KUBEVIRT_NS     = "kubevirt"
_ankavm_DATA_DIR = Path("/var/lib/ankavm/kubevirt_exports")


# ── Persistent store ──────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("kubevirt load fail: %s", e)
    return {"imports": {}, "exports": {}}


def _save(data: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except Exception as e:
        log.warning("kubevirt save fail: %s", e)


# ── kubectl helper ────────────────────────────────────────────────────────────

def _kubectl(args: list, timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


# ── virsh helper ──────────────────────────────────────────────────────────────

def _get_ankavm_vm(vm_id: str) -> Optional[dict]:
    """Get ankavm VM info from virsh."""
    try:
        r = subprocess.run(
            ["virsh", "dominfo", vm_id],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return None
        info: dict = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                info[k.strip().lower().replace(" ", "_")] = v.strip()
        return info
    except Exception:
        return None


def _get_vm_xml(vm_id: str) -> Optional[str]:
    """Get libvirt XML for a VM."""
    try:
        r = subprocess.run(
            ["virsh", "dumpxml", vm_id],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def detect_kubevirt() -> dict:
    """Detect KubeVirt installation in the cluster.

    Returns:
        dict with keys: detected, namespace, version, phase
    """
    rc, out, _ = _kubectl(["get", "kubevirt", "--all-namespaces", "-o", "json"])
    if rc != 0 or not out.strip():
        return {"detected": False, "namespace": None, "version": None, "phase": None}
    try:
        obj   = json.loads(out)
        items = obj.get("items", [])
        if not items:
            return {"detected": False, "namespace": None, "version": None, "phase": None}
        kv     = items[0]
        meta   = kv.get("metadata", {})
        status = kv.get("status", {})
        return {
            "detected":  True,
            "namespace": meta.get("namespace", _KUBEVIRT_NS),
            "version":   status.get("observedKubeVirtVersion"),
            "phase":     status.get("phase"),
            "conditions":[
                {"type": c.get("type"), "status": c.get("status")}
                for c in status.get("conditions", [])
            ],
        }
    except Exception as e:
        log.warning("detect_kubevirt parse fail: %s", e)
        return {"detected": False, "error": str(e)}


def import_from_kubevirt(vmi_name: str, namespace: str = "default") -> dict:
    """Import a KubeVirt VirtualMachineInstance as an ankavm VM record.

    This reads the VMI spec from Kubernetes and creates a corresponding
    ankavm VM configuration record (actual VM import / disk migration
    is outside scope of this call).

    Returns:
        dict with keys: ok, vm_id, name, message
    """
    rc, out, stderr = _kubectl(
        ["get", "vmi", vmi_name, "-n", namespace, "-o", "json"]
    )
    if rc != 0:
        return {"ok": False, "vm_id": None, "name": vmi_name,
                "message": f"kubectl get vmi failed: {stderr.strip()}"}
    try:
        vmi    = json.loads(out)
        meta   = vmi.get("metadata", {})
        spec   = vmi.get("spec", {})
        domain = spec.get("domain", {})
        memory = domain.get("memory", {}).get("guest", "1Gi")
        cpus   = domain.get("cpu", {}).get("cores", 1)
        name   = meta.get("name", vmi_name)

        # Parse memory string (e.g., "2Gi" → 2048 MB)
        mem_mb = 1024
        try:
            if memory.endswith("Gi"):
                mem_mb = int(memory[:-2]) * 1024
            elif memory.endswith("Mi"):
                mem_mb = int(memory[:-2])
            elif memory.endswith("G"):
                mem_mb = int(memory[:-1]) * 1024
        except Exception:
            pass

        vm_record = {
            "name":        name,
            "memory_mb":   mem_mb,
            "vcpus":       cpus,
            "source":      "kubevirt",
            "source_ns":   namespace,
            "imported_at": time.time(),
            "vmi_uid":     meta.get("uid"),
        }

        with _lock:
            data = _load()
            data["imports"][name] = vm_record
            _save(data)

        log.info("kubevirt import: vmi=%s ns=%s mem=%dMB cpus=%d", name, namespace, mem_mb, cpus)
        return {
            "ok":      True,
            "vm_id":   name,
            "name":    name,
            "message": f"VMI '{name}' imported (mem={mem_mb}MB, cpus={cpus}). "
                       "Disk migration must be performed separately.",
            "record":  vm_record,
        }
    except Exception as e:
        log.warning("import_from_kubevirt fail vmi=%s: %s", vmi_name, e)
        return {"ok": False, "vm_id": None, "name": vmi_name, "message": str(e)}


def export_to_kubevirt(vm_id: str) -> dict:
    """Generate a KubeVirt VirtualMachine YAML for an ankavm VM.

    Returns:
        dict with keys: ok, vm_id, yaml, filename, message
    """
    info = _get_ankavm_vm(vm_id)
    if not info:
        # Use defaults if virsh not available
        info = {"name": vm_id, "used_memory": "1024000 KiB", "cpu(s)": "1"}

    name    = info.get("name", vm_id)
    mem_kib = info.get("used_memory", "1048576 KiB")
    mem_mi  = 1024
    try:
        mem_mi = int(mem_kib.split()[0]) // 1024
    except Exception:
        pass
    cpus = 1
    try:
        cpus = int(info.get("cpu(s)", "1"))
    except Exception:
        pass

    kubevirt_yaml = f"""\
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: {name}
  labels:
    ankavm.io/source: "ankavm"
    ankavm.io/vm-id: "{vm_id}"
    ankavm.io/version: "2.5.10"
spec:
  running: false
  template:
    metadata:
      labels:
        kubevirt.io/vm: {name}
        ankavm.io/vm-id: "{vm_id}"
    spec:
      domain:
        cpu:
          cores: {cpus}
          sockets: 1
          threads: 1
        memory:
          guest: {mem_mi}Mi
        resources:
          requests:
            memory: {mem_mi}Mi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
            - name: cloudinit
              disk:
                bus: virtio
          interfaces:
            - name: default
              masquerade: {{}}
          rng: {{}}
        machine:
          type: q35
        features:
          acpi: {{}}
          smm:
            enabled: true
        firmware:
          bootloader:
            efi:
              secureBoot: false
      networks:
        - name: default
          pod: {{}}
      volumes:
        - name: rootdisk
          dataVolume:
            name: {name}-root
        - name: cloudinit
          cloudInitNoCloud:
            userData: |
              #cloud-config
              hostname: {name}
              chpasswd:
                expire: false
  dataVolumeTemplates:
    - metadata:
        name: {name}-root
      spec:
        storage:
          resources:
            requests:
              storage: 20Gi
          storageClassName: ankavm-standard
        source:
          blank: {{}}
"""

    filename = f"{name}_kubevirt_vm.yaml"
    out_path = _ankavm_DATA_DIR / filename

    with _lock:
        data = _load()
        data["exports"][vm_id] = {
            "vm_id":      vm_id,
            "name":       name,
            "exported_at":time.time(),
            "filename":   filename,
        }
        _save(data)

    try:
        _ankavm_DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".yaml.tmp")
        tmp.write_text(kubevirt_yaml, encoding="utf-8")
        tmp.replace(out_path)
    except Exception as e:
        log.warning("kubevirt export write fail vm=%s: %s", vm_id, e)

    log.info("kubevirt export: vm=%s -> %s", vm_id, filename)
    return {
        "ok":       True,
        "vm_id":    vm_id,
        "name":     name,
        "yaml":     kubevirt_yaml,
        "filename": filename,
        "message":  f"KubeVirt VirtualMachine YAML generated for '{name}'.",
    }


def list_kubevirt_vms() -> list:
    """List KubeVirt VirtualMachineInstances from the cluster."""
    rc, out, _ = _kubectl(["get", "vmi", "--all-namespaces", "-o", "json"])
    if rc != 0 or not out.strip():
        return []
    try:
        obj  = json.loads(out)
        vms  = []
        for item in obj.get("items", []):
            meta   = item.get("metadata", {})
            status = item.get("status", {})
            spec   = item.get("spec", {})
            domain = spec.get("domain", {})
            vms.append({
                "name":          meta.get("name"),
                "namespace":     meta.get("namespace"),
                "phase":         status.get("phase"),
                "ip_address":    status.get("interfaces", [{}])[0].get("ipAddress") if status.get("interfaces") else None,
                "node":          status.get("nodeName"),
                "vcpus":         domain.get("cpu", {}).get("cores", 1),
                "memory":        domain.get("memory", {}).get("guest"),
                "creation_time": meta.get("creationTimestamp"),
            })
        return vms
    except Exception as e:
        log.warning("kubevirt list_vms parse fail: %s", e)
        return []






