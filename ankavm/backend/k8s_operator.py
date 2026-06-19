"""
k8s_operator.py â€” Kubernetes Operator for ankavm VMs
ankavm v2.5.10 Cloud/K8s

Features:
  - generate_crd() â€” ankavmVM CRD YAML (CustomResourceDefinition)
  - generate_operator_manifests() â€” Operator Deployment + RBAC YAML
  - list_managed_vms() â€” list ankavmVM CRs from cluster
  - reconcile_status() â€” summarize operator reconcile loop state

Config persisted to /var/lib/ankavm/k8s_operator.json
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

log = logging.getLogger("k8s_operator")

_STATE_FILE    = Path("/var/lib/ankavm/k8s_operator.json")
_lock          = threading.Lock()

_OPERATOR_IMAGE  = "ghcr.io/ankavm/vm-operator:v2.5.10"
_CRD_GROUP       = "ankavm.io"
_CRD_VERSION     = "v1alpha1"
_CRD_KIND        = "ankavmVM"
_CRD_PLURAL      = "ankavmvms"
_CRD_SINGULAR    = "ankavmvm"
_OPERATOR_NS     = "ankavm-system"


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("k8s_operator load fail: %s", e)
    return {"reconcile_count": 0, "last_reconcile": None}


def _save(data: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except Exception as e:
        log.warning("k8s_operator save fail: %s", e)


# â”€â”€ kubectl helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _kubectl(args: list, timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_crd() -> str:
    """Generate ankavmVM CustomResourceDefinition YAML."""
    crd_yaml = f"""\
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: {_CRD_PLURAL}.{_CRD_GROUP}
  annotations:
    ankavm.io/version: "2.5.10"
spec:
  group: {_CRD_GROUP}
  versions:
    - name: {_CRD_VERSION}
      served: true
      storage: true
      subresources:
        status: {{}}
      additionalPrinterColumns:
        - name: State
          type: string
          jsonPath: .status.state
        - name: vCPUs
          type: integer
          jsonPath: .spec.vcpus
        - name: Memory
          type: string
          jsonPath: .spec.memoryMb
        - name: Age
          type: date
          jsonPath: .metadata.creationTimestamp
      schema:
        openAPIV3Schema:
          type: object
          required:
            - spec
          properties:
            spec:
              type: object
              required:
                - name
              properties:
                name:
                  type: string
                  description: "VM name on ankavm hypervisor"
                vcpus:
                  type: integer
                  minimum: 1
                  maximum: 256
                  default: 1
                  description: "Number of virtual CPUs"
                memoryMb:
                  type: integer
                  minimum: 256
                  default: 1024
                  description: "RAM in MiB"
                diskGb:
                  type: integer
                  minimum: 1
                  default: 20
                  description: "Root disk size in GiB"
                osImage:
                  type: string
                  description: "Cloud image path or URL"
                network:
                  type: string
                  default: "virbr0"
                  description: "Network bridge name"
                cloudInit:
                  type: object
                  x-kubernetes-preserve-unknown-fields: true
                  description: "Cloud-init user-data"
                ankavmApiUrl:
                  type: string
                  description: "ankavm API base URL (overrides operator default)"
                autoStart:
                  type: boolean
                  default: true
                  description: "Auto-start VM on host boot"
            status:
              type: object
              properties:
                state:
                  type: string
                  enum: ["Pending", "Creating", "Running", "Stopped", "Error", "Deleting"]
                vmId:
                  type: string
                ipAddress:
                  type: string
                lastReconcileTime:
                  type: string
                  format: date-time
                message:
                  type: string
                conditions:
                  type: array
                  items:
                    type: object
                    properties:
                      type:
                        type: string
                      status:
                        type: string
                      reason:
                        type: string
                      message:
                        type: string
                      lastTransitionTime:
                        type: string
  scope: Namespaced
  names:
    plural: {_CRD_PLURAL}
    singular: {_CRD_SINGULAR}
    kind: {_CRD_KIND}
    shortNames:
      - ovm
      - oxvm
    categories:
      - ankavm
"""
    log.info("k8s_operator CRD yaml generated")
    return crd_yaml


def generate_operator_manifests() -> dict:
    """Generate Operator Deployment + RBAC YAML."""
    namespace_yaml = f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {_OPERATOR_NS}
  labels:
    app.kubernetes.io/managed-by: ankavm
"""

    rbac_yaml = f"""\
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ankavm-vm-operator
  namespace: {_OPERATOR_NS}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ankavm-vm-operator-role
rules:
  - apiGroups: ["{_CRD_GROUP}"]
    resources: ["{_CRD_PLURAL}", "{_CRD_PLURAL}/status", "{_CRD_PLURAL}/finalizers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["events", "configmaps", "secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ankavm-vm-operator-binding
subjects:
  - kind: ServiceAccount
    name: ankavm-vm-operator
    namespace: {_OPERATOR_NS}
roleRef:
  kind: ClusterRole
  name: ankavm-vm-operator-role
  apiGroup: rbac.authorization.k8s.io
"""

    deployment_yaml = f"""\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ankavm-vm-operator
  namespace: {_OPERATOR_NS}
  labels:
    app: ankavm-vm-operator
    version: "2.5.10"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ankavm-vm-operator
  template:
    metadata:
      labels:
        app: ankavm-vm-operator
    spec:
      serviceAccountName: ankavm-vm-operator
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
      containers:
        - name: operator
          image: {_OPERATOR_IMAGE}
          imagePullPolicy: IfNotPresent
          env:
            - name: ankavm_API_URL
              valueFrom:
                configMapKeyRef:
                  name: ankavm-operator-config
                  key: api_url
            - name: ankavm_API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ankavm-operator-secret
                  key: api-token
            - name: LEADER_ELECTION_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: OPERATOR_NAMESPACE
              value: {_OPERATOR_NS}
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "200m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8081
            initialDelaySeconds: 15
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8081
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: ankavm-operator-config
  namespace: {_OPERATOR_NS}
data:
  api_url: "http://ankavm-api.{_OPERATOR_NS}.svc.cluster.local:5000"
  reconcile_interval_seconds: "30"
  max_concurrent_reconciles: "5"
"""

    log.info("k8s_operator manifests generated")
    return {
        "namespace_yaml":   namespace_yaml,
        "rbac_yaml":        rbac_yaml,
        "deployment_yaml":  deployment_yaml,
        "operator_version": "2.5.10",
        "crd_group":        _CRD_GROUP,
        "crd_kind":         _CRD_KIND,
    }


def list_managed_vms() -> list:
    """List ankavmVM custom resources from the cluster."""
    rc, out, _ = _kubectl(
        ["get", f"{_CRD_PLURAL}.{_CRD_GROUP}", "--all-namespaces", "-o", "json"]
    )
    if rc != 0 or not out.strip():
        return []
    try:
        obj  = json.loads(out)
        vms  = []
        for item in obj.get("items", []):
            meta   = item.get("metadata", {})
            spec   = item.get("spec", {})
            status = item.get("status", {})
            vms.append({
                "name":        meta.get("name"),
                "namespace":   meta.get("namespace"),
                "vm_name":     spec.get("name"),
                "vcpus":       spec.get("vcpus", 1),
                "memory_mb":   spec.get("memoryMb", 1024),
                "state":       status.get("state", "Unknown"),
                "vm_id":       status.get("vmId"),
                "ip_address":  status.get("ipAddress"),
                "last_reconcile": status.get("lastReconcileTime"),
            })
        return vms
    except Exception as e:
        log.warning("k8s_operator list_managed_vms parse fail: %s", e)
        return []


def reconcile_status() -> dict:
    """Summarize operator reconcile loop state."""
    # Check operator deployment
    rc, out, _ = _kubectl(
        ["get", "deployment", "ankavm-vm-operator", "-n", _OPERATOR_NS, "-o", "json"]
    )
    operator_running  = False
    operator_replicas = 0
    operator_ready    = 0
    if rc == 0 and out.strip():
        try:
            dep    = json.loads(out)
            status = dep.get("status", {})
            operator_replicas = status.get("replicas", 0)
            operator_ready    = status.get("readyReplicas", 0)
            operator_running  = operator_ready > 0
        except Exception:
            pass

    # Count managed VMs
    vms         = list_managed_vms()
    state_counts: dict = {}
    for vm in vms:
        s = vm.get("state", "Unknown")
        state_counts[s] = state_counts.get(s, 0) + 1

    with _lock:
        data = _load()
        data["last_reconcile"] = time.time()
        _save(data)

    return {
        "operator_running":  operator_running,
        "operator_replicas": operator_replicas,
        "operator_ready":    operator_ready,
        "managed_vms_total": len(vms),
        "vm_states":         state_counts,
        "crd_group":         _CRD_GROUP,
        "crd_kind":          _CRD_KIND,
        "operator_namespace":_OPERATOR_NS,
    }






