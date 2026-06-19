"""ankavm â†” KubeVirt Bridge (v2.9).

Translates KubeVirt VirtualMachine CRs into native ankavm VM definitions
so a single ankavm cluster can serve as the hypervisor backing for a
KubeVirt-managed Kubernetes cluster. Watches a kubeconfig-supplied
cluster for VirtualMachine and VirtualMachineInstance objects and
reconciles them against `vm_manager`.

State: /var/lib/ankavm/kubevirt_links.json
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("ankavm.kubevirt")
_CATALOG = Path("/var/lib/ankavm/kubevirt_links.json")
_LOCK = threading.Lock()


def _load() -> dict:
    if not _CATALOG.exists():
        return {"links": []}
    try:
        return json.loads(_CATALOG.read_text(encoding="utf-8"))
    except Exception:
        return {"links": []}


def _save(d: dict) -> None:
    _CATALOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, _CATALOG)


def list_links() -> list:
    return _load().get("links", [])


def register_cluster(name: str, kubeconfig_b64: str,
                     watch_namespace: str = "") -> dict:
    """Register a Kubernetes cluster whose KubeVirt CRs we should serve.
    The kubeconfig is stored verbatim â€” operators must rotate it like any
    other long-lived credential."""
    link = {
        "id": name,
        "name": name,
        "watch_namespace": watch_namespace or "*",
        "kubeconfig_b64": kubeconfig_b64,
        "state": "registered",
        "added_at": time.time(),
    }
    with _LOCK:
        d = _load()
        d["links"] = [l for l in d["links"] if l["id"] != name]
        d["links"].append(link)
        _save(d)
    log.info("KubeVirt cluster registered: %s (ns=%s)", name, watch_namespace)
    safe = dict(link)
    safe["kubeconfig_b64"] = "***"
    return {"ok": True, "link": safe}


def unregister(name: str) -> dict:
    with _LOCK:
        d = _load()
        new = [l for l in d["links"] if l["id"] != name]
        if len(new) == len(d["links"]):
            return {"ok": False, "error": "not found"}
        d["links"] = new
        _save(d)
    return {"ok": True, "name": name}


def translate_vmi_to_ankavm(vmi_spec: dict) -> dict:
    """Lower a KubeVirt VirtualMachineInstance spec to an ankavm VM config
    skeleton that vm_manager.create_vm() can consume."""
    if not isinstance(vmi_spec, dict):
        return {"ok": False, "error": "vmi_spec must be a dict"}
    domain = vmi_spec.get("domain", {})
    cpu = domain.get("cpu", {})
    mem = domain.get("resources", {}).get("requests", {}).get("memory", "1Gi")
    out = {
        "name": vmi_spec.get("metadata", {}).get("name", "kubevirt-vm"),
        "vcpus": int(cpu.get("cores", 1)),
        "memory_mb": _parse_mem(mem),
        "disks": [d for d in domain.get("devices", {}).get("disks", [])],
        "interfaces": [i for i in domain.get("devices", {}).get("interfaces", [])],
        "_source": "kubevirt",
    }
    return {"ok": True, "vm_config": out}


def _parse_mem(s: str) -> int:
    if not isinstance(s, str):
        return 1024
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024}
    for u, factor in units.items():
        if s.endswith(u):
            try:
                return int(float(s[:-len(u)]) * factor)
            except Exception:
                return 1024
    try:
        return int(s) // (1024 * 1024)
    except Exception:
        return 1024






