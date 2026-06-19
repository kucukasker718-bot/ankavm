"""
service_mesh.py â€” Service Mesh Integration (Istio/Linkerd discovery + sidecar config)
ankavm v2.5.9 Network Advanced 2

Features:
  - detect_mesh() â€” istioctl/linkerd binary + kubeconfig detection
  - register_service(name, vm_id, port, protocol) â€” mesh service registry
  - list_services(), get_service(name), delete_service(name)
  - generate_sidecar_config(service_name) â€” Envoy/Istio sidecar YAML
  - get_mtls_status() â€” mesh mTLS status

Config persisted to /var/lib/ankavm/service_mesh.json
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

log = logging.getLogger("service_mesh")

_MESH_FILE = Path("/var/lib/ankavm/service_mesh.json")
_lock      = threading.Lock()

_KUBECONFIG_PATHS = [
    Path("/etc/ankavm/kubeconfig"),
    Path.home() / ".kube" / "config",
    Path("/root/.kube/config"),
]


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _MESH_FILE.exists():
            return json.loads(_MESH_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("mesh load fail: %s", e)
    return {"services": {}}


def _save(data: dict) -> None:
    try:
        _MESH_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MESH_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_MESH_FILE)
    except Exception as e:
        log.warning("mesh save fail: %s", e)


# â”€â”€ Binary detection helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _which(binary: str) -> Optional[str]:
    try:
        r = subprocess.run(["which", binary], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _kubeconfig_path() -> Optional[str]:
    for p in _KUBECONFIG_PATHS:
        if p.exists():
            return str(p)
    return None


def _run_istioctl(*args, timeout: int = 10) -> dict:
    istioctl = _which("istioctl")
    if not istioctl:
        return {"ok": False, "error": "istioctl not found"}
    env_extra = {}
    kc = _kubeconfig_path()
    if kc:
        env_extra["KUBECONFIG"] = kc
    try:
        import os
        env = {**os.environ, **env_extra}
        r = subprocess.run(
            [istioctl] + list(args),
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_linkerd(*args, timeout: int = 10) -> dict:
    linkerd = _which("linkerd")
    if not linkerd:
        return {"ok": False, "error": "linkerd not found"}
    try:
        r = subprocess.run(
            [linkerd] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_mesh() -> dict:
    """
    Detect available service mesh tooling.
    Returns {istio, linkerd, available, kubeconfig}.
    """
    istioctl = _which("istioctl")
    linkerd  = _which("linkerd")
    kc       = _kubeconfig_path()

    istio_status  = "not_found"
    linkerd_status = "not_found"

    if istioctl:
        r = _run_istioctl("version", "--short", timeout=8)
        istio_status = "available" if r.get("ok") else "binary_found_unreachable"

    if linkerd:
        r = _run_linkerd("version", "--short", timeout=8)
        linkerd_status = "available" if r.get("ok") else "binary_found_unreachable"

    return {
        "istio":       {"status": istio_status,  "binary": istioctl},
        "linkerd":     {"status": linkerd_status, "binary": linkerd},
        "kubeconfig":  kc,
        "available":   istio_status == "available" or linkerd_status == "available",
    }


def register_service(name: str, vm_id: str, port: int, protocol: str = "tcp") -> dict:
    """
    Register a VM service in the mesh service registry.
    protocol: 'tcp' | 'http' | 'grpc' | 'https'
    """
    with _lock:
        data = _load()
        svcs = data.setdefault("services", {})

        svcs[name] = {
            "name":         name,
            "vm_id":        vm_id,
            "port":         port,
            "protocol":     protocol,
            "registered_at": int(time.time()),
            "mesh_injected": False,
        }
        _save(data)

        return {
            "ok":       True,
            "name":     name,
            "vm_id":    vm_id,
            "port":     port,
            "protocol": protocol,
        }


def list_services() -> list:
    with _lock:
        data = _load()
        return list(data.get("services", {}).values())


def get_service(name: str) -> Optional[dict]:
    with _lock:
        return _load().get("services", {}).get(name)


def delete_service(name: str) -> dict:
    with _lock:
        data = _load()
        svcs = data.get("services", {})
        if name not in svcs:
            return {"ok": False, "error": "Service not found"}
        del svcs[name]
        _save(data)
        return {"ok": True, "name": name}


def generate_sidecar_config(service_name: str) -> dict:
    """
    Generate Envoy/Istio sidecar YAML for a registered service.
    Returns YAML string â€” deploy manually via kubectl/istioctl.
    """
    svc = get_service(service_name)
    if not svc:
        return {"ok": False, "error": "Service not found"}

    port     = svc.get("port", 80)
    protocol = svc.get("protocol", "tcp").upper()
    vm_id    = svc.get("vm_id", "unknown")

    # Determine Istio traffic policy protocol
    istio_proto = {
        "HTTP":  "HTTP",
        "HTTPS": "TLS",
        "GRPC":  "GRPC",
        "TCP":   "TCP",
    }.get(protocol, "TCP")

    yaml_str = f"""\
# ankavm v2.5.9 â€” Generated Sidecar Config for '{service_name}'
# Deploy: kubectl apply -f sidecar-{service_name}.yaml
---
apiVersion: networking.istio.io/v1alpha3
kind: Sidecar
metadata:
  name: {service_name}
  namespace: ankavm
  labels:
    ankavm.io/vm-id: "{vm_id}"
    ankavm.io/service: "{service_name}"
spec:
  ingress:
    - port:
        number: {port}
        protocol: {istio_proto}
        name: {service_name}-port
      defaultEndpoint: 127.0.0.1:{port}
  egress:
    - hosts:
        - "./*"
        - "istio-system/*"
---
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: {service_name}-mtls
  namespace: ankavm
spec:
  host: {service_name}.ankavm.svc.cluster.local
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        h2UpgradePolicy: UPGRADE
    portLevelSettings:
      - port:
          number: {port}
        tls:
          mode: ISTIO_MUTUAL
"""

    return {
        "ok":           True,
        "service_name": service_name,
        "yaml":         yaml_str,
        "note":         "Deploy manually: kubectl apply -f <file>. This config is not applied automatically.",
    }


def get_mtls_status() -> dict:
    """
    Query mTLS status from the active mesh.
    Tries istioctl check-inject; falls back to stored registry info.
    """
    mesh = detect_mesh()

    if mesh["istio"]["status"] == "available":
        r = _run_istioctl("x", "check-inject", "-n", "ankavm", timeout=15)
        if r.get("ok"):
            return {
                "ok":      True,
                "mesh":    "istio",
                "raw":     r.get("stdout", ""),
                "mtls":    "STRICT" in r.get("stdout", "").upper(),
            }

    if mesh["linkerd"]["status"] == "available":
        r = _run_linkerd("check", "--proxy", timeout=15)
        return {
            "ok":   True,
            "mesh": "linkerd",
            "mtls": r.get("ok", False),
            "raw":  r.get("stdout", ""),
        }

    # No live mesh â€” return registry summary
    svcs = list_services()
    return {
        "ok":            True,
        "mesh":          "none",
        "mtls":          False,
        "services_count": len(svcs),
        "note":          "No active service mesh detected; mTLS status unavailable.",
    }






