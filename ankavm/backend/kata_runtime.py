"""
kata_runtime.py â€” Kata Containers Runtime Manager for ankavm
ankavm v2.5.11 Modern Workloads

Features:
  - detect_kata() â€” kata-runtime binary + containerd config {available, version}
  - list_kata_containers() â€” kata pod/container list via crictl or ctr
  - generate_runtime_class() â€” Kubernetes RuntimeClass YAML for kata
  - get_kata_config() â€” summary of kata configuration.toml

No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("kata_runtime")

_lock = threading.Lock()

_KATA_CONFIG_PATHS = [
    "/opt/kata/share/defaults/kata-containers/configuration.toml",
    "/etc/kata-containers/configuration.toml",
    "/usr/share/defaults/kata-containers/configuration.toml",
]

_KATA_BINARIES = [
    "kata-runtime",
    "/opt/kata/bin/kata-runtime",
    "/usr/local/bin/kata-runtime",
]


# â”€â”€ Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_kata() -> dict:
    """Check if kata-runtime is installed and containerd is configured for it."""
    result = {
        "available":           False,
        "version":             None,
        "binary":              None,
        "containerd_config_ok": False,
        "crictl_ok":           False,
        "error":               None,
    }
    # Find binary
    binary = None
    for candidate in _KATA_BINARIES:
        try:
            if "/" in candidate:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    binary = candidate
                    break
            else:
                r = subprocess.run(["which", candidate], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    binary = r.stdout.strip()
                    break
        except Exception:
            continue
    if not binary:
        result["error"] = "kata-runtime binary not found"
        return result
    result["binary"] = binary
    # Version
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        line = (r.stdout or r.stderr or "").strip().splitlines()
        result["version"] = line[0] if line else "unknown"
    except Exception as e:
        result["version"] = "unknown"
        log.debug("kata version error: %s", e)
    # containerd config check
    containerd_cfg = "/etc/containerd/config.toml"
    if os.path.exists(containerd_cfg):
        try:
            content = Path(containerd_cfg).read_text(encoding="utf-8", errors="replace")
            result["containerd_config_ok"] = "kata" in content.lower()
        except Exception:
            pass
    # crictl availability
    try:
        r = subprocess.run(["which", "crictl"], capture_output=True, timeout=5)
        result["crictl_ok"] = r.returncode == 0
    except Exception:
        pass
    result["available"] = True
    return result


# â”€â”€ Container listing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def list_kata_containers() -> list:
    """
    List running Kata containers/pods using crictl or ctr.
    Returns list of container dicts. Empty list if tooling unavailable.
    """
    containers = []
    # Try crictl first
    try:
        r = subprocess.run(
            ["crictl", "ps", "-o", "json"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            for c in data.get("containers", []):
                annotations = c.get("annotations", {}) or {}
                runtime_type = annotations.get("io.kubernetes.cri.runtime-handler", "")
                if "kata" in str(runtime_type).lower() or "kata" in str(c.get("runtime", "")).lower():
                    containers.append({
                        "id":           c.get("id", "")[:12],
                        "name":         c.get("metadata", {}).get("name", ""),
                        "state":        c.get("state", ""),
                        "image":        c.get("image", {}).get("image", ""),
                        "runtime":      runtime_type or "kata",
                        "pod_sandbox":  c.get("podSandboxId", "")[:12],
                        "source":       "crictl",
                    })
    except FileNotFoundError:
        log.debug("crictl not found, trying ctr")
    except Exception as e:
        log.debug("crictl list fail: %s", e)
    # Try ctr if crictl returned nothing
    if not containers:
        try:
            r = subprocess.run(
                ["ctr", "containers", "ls"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                lines = r.stdout.strip().splitlines()
                for line in lines[1:]:  # skip header
                    parts = line.split()
                    if len(parts) >= 1:
                        containers.append({
                            "id":      parts[0][:12],
                            "name":    parts[0],
                            "state":   "unknown",
                            "image":   parts[1] if len(parts) > 1 else "",
                            "runtime": "kata",
                            "source":  "ctr",
                        })
        except Exception as e:
            log.debug("ctr list fail: %s", e)
    return containers


# â”€â”€ RuntimeClass YAML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_runtime_class() -> dict:
    """Generate a Kubernetes RuntimeClass YAML for Kata Containers."""
    yaml_text = (
        "apiVersion: node.k8s.io/v1\n"
        "kind: RuntimeClass\n"
        "metadata:\n"
        "  name: kata\n"
        "handler: kata\n"
        "overhead:\n"
        "  podFixed:\n"
        "    memory: \"160Mi\"\n"
        "    cpu: \"250m\"\n"
        "scheduling:\n"
        "  nodeClassification:\n"
        "    tolerations:\n"
        "    - key: \"kata-containers.io/enabled\"\n"
        "      operator: \"Exists\"\n"
        "      effect: \"NoSchedule\"\n"
    )
    return {"runtime_class_yaml": yaml_text, "handler": "kata", "overhead_memory_mi": 160}


# â”€â”€ Config summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_kata_config() -> dict:
    """Return a summary of the Kata configuration.toml."""
    result: dict = {
        "config_path": None,
        "hypervisor":  None,
        "kernel":      None,
        "image":       None,
        "agent":       None,
        "raw_excerpt": None,
        "error":       None,
    }
    config_path = None
    for p in _KATA_CONFIG_PATHS:
        if os.path.exists(p):
            config_path = p
            break
    if not config_path:
        result["error"] = "configuration.toml not found"
        return result
    result["config_path"] = config_path
    try:
        content = Path(config_path).read_text(encoding="utf-8", errors="replace")
        # Extract key fields (simple line-based parse, no toml lib)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("hypervisor") and "[" in stripped:
                result["hypervisor"] = stripped.strip("[]").replace("hypervisor.", "")
            elif stripped.startswith("kernel ="):
                result["kernel"] = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("image ="):
                result["image"] = stripped.split("=", 1)[1].strip().strip('"')
            elif stripped.startswith("agent") and "[" in stripped:
                result["agent"] = stripped.strip("[]").replace("agent.", "")
        # Provide a short excerpt (first 40 non-empty, non-comment lines)
        excerpt_lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
        result["raw_excerpt"] = "\n".join(excerpt_lines[:40])
    except Exception as e:
        result["error"] = str(e)
    return result






