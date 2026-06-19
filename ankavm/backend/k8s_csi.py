"""
k8s_csi.py â€” Kubernetes CSI (Container Storage Interface) for ankavm
ankavm v2.5.10 Cloud/K8s

Features:
  - generate_csi_manifests() â€” DaemonSet + StorageClass YAML for ankavm CSI driver
  - list_volumes() â€” list PersistentVolumes backed by ankavm storage
  - create_volume_claim(name, size_gb, storage_class) â€” create PVC spec
  - get_csi_status() â€” CSI driver health / node registration status

Config persisted to /var/lib/ankavm/k8s_csi.json
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

log = logging.getLogger("k8s_csi")

_CSI_FILE = Path("/var/lib/ankavm/k8s_csi.json")
_lock     = threading.Lock()

_DRIVER_NAME   = "csi.ankavm.io"
_DRIVER_IMAGE  = "ghcr.io/ankavm/csi-driver:v2.5.10"
_NODE_IMAGE    = "ghcr.io/ankavm/csi-node:v2.5.10"


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _CSI_FILE.exists():
            return json.loads(_CSI_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("k8s_csi load fail: %s", e)
    return {"volumes": {}, "claims": {}}


def _save(data: dict) -> None:
    try:
        _CSI_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CSI_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_CSI_FILE)
    except Exception as e:
        log.warning("k8s_csi save fail: %s", e)


# â”€â”€ kubectl helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _kubectl(args: list, timeout: int = 15) -> tuple[int, str, str]:
    """Run kubectl and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_csi_manifests() -> dict:
    """Generate CSI DaemonSet + StorageClass YAML manifests.

    Returns:
        dict with keys: daemonset_yaml, storageclass_yaml, controller_yaml
    """
    daemonset_yaml = f"""\
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: ankavm-csi-node
  namespace: kube-system
  labels:
    app: ankavm-csi-node
    version: "2.5.10"
spec:
  selector:
    matchLabels:
      app: ankavm-csi-node
  template:
    metadata:
      labels:
        app: ankavm-csi-node
    spec:
      hostNetwork: true
      hostPID: true
      priorityClassName: system-node-critical
      tolerations:
        - operator: Exists
      containers:
        - name: ankavm-csi-driver
          image: {_NODE_IMAGE}
          imagePullPolicy: IfNotPresent
          securityContext:
            privileged: true
            capabilities:
              add: ["SYS_ADMIN"]
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: ankavm_API_URL
              value: "http://ankavm-api.ankavm-system.svc.cluster.local:5000"
            - name: ankavm_API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ankavm-csi-secret
                  key: api-token
          volumeMounts:
            - name: plugin-dir
              mountPath: /csi
            - name: pods-mount-dir
              mountPath: /var/lib/kubelet
              mountPropagation: Bidirectional
            - name: device-dir
              mountPath: /dev
            - name: sys-dir
              mountPath: /sys
            - name: host-root
              mountPath: /host
              mountPropagation: HostToContainer
          ports:
            - name: healthz
              containerPort: 9808
              protocol: TCP
        - name: node-driver-registrar
          image: registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.9.0
          args:
            - "--csi-address=/csi/csi.sock"
            - "--kubelet-registration-path=/var/lib/kubelet/plugins/{_DRIVER_NAME}/csi.sock"
          volumeMounts:
            - name: plugin-dir
              mountPath: /csi
            - name: registration-dir
              mountPath: /registration
      volumes:
        - name: plugin-dir
          hostPath:
            path: /var/lib/kubelet/plugins/{_DRIVER_NAME}
            type: DirectoryOrCreate
        - name: pods-mount-dir
          hostPath:
            path: /var/lib/kubelet
            type: Directory
        - name: device-dir
          hostPath:
            path: /dev
        - name: sys-dir
          hostPath:
            path: /sys
        - name: host-root
          hostPath:
            path: /
        - name: registration-dir
          hostPath:
            path: /var/lib/kubelet/plugins_registry
            type: Directory
"""

    controller_yaml = f"""\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ankavm-csi-controller
  namespace: kube-system
  labels:
    app: ankavm-csi-controller
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ankavm-csi-controller
  template:
    metadata:
      labels:
        app: ankavm-csi-controller
    spec:
      serviceAccountName: ankavm-csi-controller-sa
      priorityClassName: system-cluster-critical
      containers:
        - name: ankavm-csi-controller
          image: {_DRIVER_IMAGE}
          imagePullPolicy: IfNotPresent
          env:
            - name: ankavm_API_URL
              value: "http://ankavm-api.ankavm-system.svc.cluster.local:5000"
            - name: ankavm_API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ankavm-csi-secret
                  key: api-token
          ports:
            - name: healthz
              containerPort: 9808
        - name: external-provisioner
          image: registry.k8s.io/sig-storage/csi-provisioner:v3.6.0
          args:
            - "--csi-address=/csi/csi.sock"
            - "--leader-election"
          volumeMounts:
            - name: socket-dir
              mountPath: /csi
        - name: external-attacher
          image: registry.k8s.io/sig-storage/csi-attacher:v4.4.0
          args:
            - "--csi-address=/csi/csi.sock"
            - "--leader-election"
          volumeMounts:
            - name: socket-dir
              mountPath: /csi
        - name: external-resizer
          image: registry.k8s.io/sig-storage/csi-resizer:v1.9.0
          args:
            - "--csi-address=/csi/csi.sock"
            - "--leader-election"
          volumeMounts:
            - name: socket-dir
              mountPath: /csi
      volumes:
        - name: socket-dir
          emptyDir: {{}}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ankavm-csi-controller-sa
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ankavm-csi-controller-role
rules:
  - apiGroups: [""]
    resources: ["persistentvolumes"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses", "csinodes", "csidrivers"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["storage.k8s.io"]
    resources: ["volumeattachments", "volumeattachments/status"]
    verbs: ["get", "list", "watch", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ankavm-csi-controller-binding
subjects:
  - kind: ServiceAccount
    name: ankavm-csi-controller-sa
    namespace: kube-system
roleRef:
  kind: ClusterRole
  name: ankavm-csi-controller-role
  apiGroup: rbac.authorization.k8s.io
"""

    storageclass_yaml = f"""\
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ankavm-standard
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: {_DRIVER_NAME}
parameters:
  pool: "default"
  replication: "1"
  fstype: "ext4"
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ankavm-replicated
provisioner: {_DRIVER_NAME}
parameters:
  pool: "default"
  replication: "3"
  fstype: "ext4"
  encryption: "aes-256-gcm"
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: storage.k8s.io/v1
kind: CSIDriver
metadata:
  name: {_DRIVER_NAME}
spec:
  attachRequired: true
  podInfoOnMount: true
  volumeLifecycleModes:
    - Persistent
    - Ephemeral
"""

    log.info("k8s_csi manifests generated")
    return {
        "daemonset_yaml":    daemonset_yaml,
        "controller_yaml":   controller_yaml,
        "storageclass_yaml": storageclass_yaml,
        "driver_name":       _DRIVER_NAME,
        "driver_version":    "2.5.10",
    }


def list_volumes() -> list:
    """List PersistentVolumes via kubectl. Returns list of volume dicts."""
    rc, out, _ = _kubectl(["get", "pv", "-o", "json"])
    if rc != 0 or not out.strip():
        # Fallback: return persisted volume list
        with _lock:
            return list(_load().get("volumes", {}).values())
    try:
        pv_list = json.loads(out)
        vols = []
        for item in pv_list.get("items", []):
            spec  = item.get("spec", {})
            meta  = item.get("metadata", {})
            phase = item.get("status", {}).get("phase", "Unknown")
            csi   = spec.get("csi", {})
            if csi.get("driver") == _DRIVER_NAME:
                vols.append({
                    "name":          meta.get("name"),
                    "capacity":      spec.get("capacity", {}).get("storage"),
                    "access_modes":  spec.get("accessModes", []),
                    "reclaim_policy":spec.get("persistentVolumeReclaimPolicy"),
                    "storage_class": spec.get("storageClassName"),
                    "phase":         phase,
                    "csi_handle":    csi.get("volumeHandle"),
                })
        return vols
    except Exception as e:
        log.warning("k8s_csi list_volumes parse fail: %s", e)
        return []


def create_volume_claim(name: str, size_gb: int, storage_class: str = "ankavm-standard") -> dict:
    """Generate and optionally apply a PersistentVolumeClaim spec.

    Returns:
        dict with keys: pvc_yaml, applied (bool), name
    """
    pvc_yaml = f"""\
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {name}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {size_gb}Gi
  storageClassName: {storage_class}
"""
    applied = False
    rc, _, stderr = _kubectl(["apply", "-f", "-"], timeout=20)
    # Note: apply via stdin is not done here to avoid piping complexity.
    # The manifest is returned for the user to apply.
    with _lock:
        data = _load()
        data["claims"][name] = {
            "name":          name,
            "size_gb":       size_gb,
            "storage_class": storage_class,
            "created_at":    time.time(),
        }
        _save(data)

    log.info("k8s_csi create_volume_claim: name=%s size=%dGi sc=%s", name, size_gb, storage_class)
    return {
        "name":          name,
        "size_gb":       size_gb,
        "storage_class": storage_class,
        "pvc_yaml":      pvc_yaml,
        "applied":       applied,
    }


def get_csi_status() -> dict:
    """Get CSI driver registration and health status."""
    rc, out, _ = _kubectl(["get", "csidrivers", _DRIVER_NAME, "-o", "json"])
    registered = rc == 0 and bool(out.strip())

    node_count   = 0
    ready_nodes  = 0
    rc2, out2, _ = _kubectl(["get", "daemonset", "ankavm-csi-node", "-n", "kube-system", "-o", "json"])
    if rc2 == 0 and out2.strip():
        try:
            ds     = json.loads(out2)
            status = ds.get("status", {})
            node_count  = status.get("desiredNumberScheduled", 0)
            ready_nodes = status.get("numberReady", 0)
        except Exception:
            pass

    return {
        "driver_name":   _DRIVER_NAME,
        "driver_version":"2.5.10",
        "registered":    registered,
        "node_count":    node_count,
        "ready_nodes":   ready_nodes,
        "healthy":       registered and (node_count == ready_nodes) and node_count > 0,
    }






