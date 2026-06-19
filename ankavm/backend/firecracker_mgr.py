"""
firecracker_mgr.py â€” Firecracker microVM Manager for ankavm
ankavm v2.5.11 Modern Workloads

Features:
  - detect_firecracker() â€” firecracker binary + KVM availability
  - create_microvm(name, vcpus, mem_mb, kernel_path, rootfs_path) â€” spawn microVM via API socket
  - list_microvms() â€” list tracked microVMs
  - stop_microvm(id) â€” stop a running microVM
  - get_microvm(id) â€” get details of a specific microVM
  - generate_config(name, vcpus, mem_mb, kernel, rootfs) â€” produce Firecracker machine-config JSON

Config persisted to /var/lib/ankavm/firecracker_vms.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("firecracker_mgr")

_DATA_FILE = Path("/var/lib/ankavm/firecracker_vms.json")
_SOCKET_DIR = Path("/var/lib/ankavm/firecracker_sockets")
_lock = threading.Lock()


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("firecracker load fail: %s", e)
    return {"vms": {}}


def _save(data: dict) -> None:
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_DATA_FILE)
    except Exception as e:
        log.warning("firecracker save fail: %s", e)


# â”€â”€ Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_firecracker() -> dict:
    """Check if Firecracker binary is available and KVM is accessible."""
    result = {
        "available": False,
        "version":   None,
        "binary":    None,
        "kvm_ok":    False,
        "error":     None,
    }
    # Find binary
    binary = None
    for candidate in ("/usr/bin/firecracker", "/usr/local/bin/firecracker", "firecracker"):
        try:
            r = subprocess.run(
                ["which", candidate] if "/" not in candidate else ["test", "-x", candidate],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                binary = candidate
                break
        except Exception:
            continue
    # Try direct which
    if not binary:
        try:
            r = subprocess.run(["which", "firecracker"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                binary = r.stdout.strip()
        except Exception:
            pass
    if not binary:
        result["error"] = "firecracker binary not found"
        return result
    result["binary"] = binary
    # Get version
    try:
        r = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5)
        line = (r.stdout or r.stderr or "").strip().splitlines()
        result["version"] = line[0] if line else "unknown"
    except Exception as e:
        result["version"] = "unknown"
        log.debug("firecracker version error: %s", e)
    # KVM check
    result["kvm_ok"] = os.access("/dev/kvm", os.R_OK | os.W_OK)
    result["available"] = result["kvm_ok"]
    if not result["kvm_ok"]:
        result["error"] = "/dev/kvm not accessible"
    return result


# â”€â”€ Config generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate_config(name: str, vcpus: int, mem_mb: int, kernel: str, rootfs: str) -> dict:
    """Generate a Firecracker machine-config JSON dict."""
    return {
        "boot-source": {
            "kernel_image_path": kernel,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
        },
        "drives": [
            {
                "drive_id":       "rootfs",
                "path_on_host":   rootfs,
                "is_root_device": True,
                "is_read_only":   False,
            }
        ],
        "machine-config": {
            "vcpu_count":      max(1, int(vcpus)),
            "mem_size_mib":    max(128, int(mem_mb)),
            "smt":             False,
        },
        "network-interfaces": [],
    }


# â”€â”€ microVM lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_microvm(
    name: str,
    vcpus: int = 1,
    mem_mb: int = 512,
    kernel_path: str = "/opt/ankavm/vmlinux",
    rootfs_path: str = "/opt/ankavm/rootfs.ext4",
) -> dict:
    """
    Create and start a Firecracker microVM.
    Generates a config file and spawns firecracker process with a UDS socket.
    Returns VM record with id, socket_path, pid, status.
    """
    det = detect_firecracker()
    if not det.get("available"):
        return {"created": False, "error": det.get("error", "firecracker unavailable")}

    vm_id = str(uuid.uuid4())[:8]
    socket_path = str(_SOCKET_DIR / f"fc-{vm_id}.sock")
    config = generate_config(name, vcpus, mem_mb, kernel_path, rootfs_path)
    config_path = str(_SOCKET_DIR / f"fc-{vm_id}-config.json")

    try:
        _SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        Path(config_path).write_text(json.dumps(config, indent=2), encoding="utf-8")
        proc = subprocess.Popen(
            [det["binary"], "--api-sock", socket_path, "--config-file", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        pid = proc.pid
    except Exception as e:
        log.warning("create_microvm spawn fail: %s", e)
        return {"created": False, "error": str(e)}

    record = {
        "id":          vm_id,
        "name":        name,
        "vcpus":       vcpus,
        "mem_mb":      mem_mb,
        "kernel_path": kernel_path,
        "rootfs_path": rootfs_path,
        "socket_path": socket_path,
        "config_path": config_path,
        "pid":         pid,
        "status":      "running",
        "created_at":  int(time.time()),
    }

    with _lock:
        data = _load()
        data["vms"][vm_id] = record
        _save(data)

    return {"created": True, "vm": record}


def list_microvms() -> list:
    """Return list of tracked microVMs."""
    with _lock:
        data = _load()
    vms = list(data.get("vms", {}).values())
    # Refresh pid status
    for vm in vms:
        pid = vm.get("pid")
        if pid and vm.get("status") == "running":
            try:
                os.kill(pid, 0)
            except OSError:
                vm["status"] = "stopped"
    return vms


def get_microvm(vm_id: str) -> Optional[dict]:
    """Return details for a specific microVM or None if not found."""
    with _lock:
        data = _load()
    vm = data.get("vms", {}).get(vm_id)
    if not vm:
        return None
    pid = vm.get("pid")
    if pid and vm.get("status") == "running":
        try:
            os.kill(pid, 0)
        except OSError:
            vm["status"] = "stopped"
    return vm


def stop_microvm(vm_id: str) -> dict:
    """Stop a running microVM by sending SIGTERM to its process."""
    with _lock:
        data = _load()
        vm = data.get("vms", {}).get(vm_id)
        if not vm:
            return {"stopped": False, "error": "vm not found"}
        pid = vm.get("pid")
        if vm.get("status") != "running":
            return {"stopped": False, "error": f"vm is already {vm.get('status')}"}
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
            except OSError as e:
                log.debug("stop_microvm kill fail: %s", e)
        vm["status"] = "stopped"
        vm["stopped_at"] = int(time.time())
        data["vms"][vm_id] = vm
        _save(data)
    return {"stopped": True, "vm_id": vm_id}






