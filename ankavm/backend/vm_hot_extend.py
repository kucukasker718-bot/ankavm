"""
ankavm VM Hot Disk Extension
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Extend VM disk without shutdown using virsh blockresize + guest growpart.
Requires QEMU guest agent for in-guest partition resize.
"""
import base64
import json
import logging
import re
import subprocess
import time

_log = logging.getLogger("ankavm.vm_hot_extend")

_GB = 1024 ** 3


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def _run_nofail(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def get_disk_info(vm_id: str) -> list:
    disks = []
    try:
        r = _run(["virsh", "domblklist", vm_id, "--details"])
    except subprocess.CalledProcessError as e:
        _log.warning("domblklist failed for %s: %s", vm_id, e.stderr.strip())
        return disks
    except Exception as e:
        _log.warning("domblklist error for %s: %s", vm_id, e)
        return disks

    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] not in ("disk", "cdrom"):
            continue
        target = parts[2]
        path = parts[3] if parts[3] != "-" else ""
        info = {
            "target": target,
            "path": path,
            "capacity_gb": None,
            "allocation_gb": None,
            "physical_gb": None,
        }
        try:
            ri = _run(["virsh", "domblkinfo", vm_id, target])
            for bline in ri.stdout.splitlines():
                bline = bline.strip()
                if bline.startswith("Capacity:"):
                    info["capacity_gb"] = round(int(bline.split(":")[1].strip()) / _GB, 2)
                elif bline.startswith("Allocation:"):
                    info["allocation_gb"] = round(int(bline.split(":")[1].strip()) / _GB, 2)
                elif bline.startswith("Physical:"):
                    info["physical_gb"] = round(int(bline.split(":")[1].strip()) / _GB, 2)
        except Exception as e:
            _log.warning("domblkinfo failed for %s/%s: %s", vm_id, target, e)
        disks.append(info)
    return disks


def check_guest_agent(vm_id: str) -> bool:
    try:
        cmd = json.dumps({"execute": "guest-ping"})
        r = _run_nofail(["virsh", "qemu-agent-command", vm_id, cmd], timeout=10)
        return r.returncode == 0 and "return" in r.stdout
    except Exception:
        return False


def _guest_exec(vm_id: str, cmd_args: list) -> dict:
    payload = json.dumps({
        "execute": "guest-exec",
        "arguments": {
            "path": cmd_args[0],
            "arg": cmd_args[1:],
            "capture-output": True,
        },
    })
    r = _run_nofail(["virsh", "qemu-agent-command", vm_id, payload], timeout=30)
    if r.returncode != 0:
        return {"success": False, "stderr": r.stderr.strip()}
    try:
        pid = json.loads(r.stdout).get("return", {}).get("pid")
    except Exception:
        return {"success": False, "stderr": "could not parse pid"}

    for _ in range(20):
        time.sleep(1)
        poll = json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}})
        pr = _run_nofail(["virsh", "qemu-agent-command", vm_id, poll], timeout=10)
        if pr.returncode != 0:
            continue
        try:
            status = json.loads(pr.stdout).get("return", {})
            if status.get("exited"):
                stdout = base64.b64decode(status.get("out-data", "")).decode("utf-8", errors="replace") if status.get("out-data") else ""
                stderr = base64.b64decode(status.get("err-data", "")).decode("utf-8", errors="replace") if status.get("err-data") else ""
                return {
                    "success": status.get("exitcode", 1) == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exitcode": status.get("exitcode"),
                }
        except Exception:
            continue
    return {"success": False, "stderr": "timeout waiting for guest-exec"}


def resize_guest_fs(vm_id: str, partition: str = "/dev/vda1") -> dict:
    results = {}
    m = re.match(r"^(/dev/[a-z]+)(\d+)$", partition)
    if m:
        results["growpart"] = _guest_exec(vm_id, ["/usr/bin/growpart", m.group(1), m.group(2)])
    else:
        results["growpart"] = {"success": False, "stderr": f"cannot parse partition: {partition}"}

    blkid_r = _guest_exec(vm_id, ["/usr/sbin/blkid", "-o", "value", "-s", "TYPE", partition])
    fs_type = blkid_r.get("stdout", "").strip() if blkid_r.get("success") else ""

    if fs_type in ("ext2", "ext3", "ext4", ""):
        results["fs_resize"] = _guest_exec(vm_id, ["/usr/sbin/resize2fs", partition])
    elif fs_type == "xfs":
        results["fs_resize"] = _guest_exec(vm_id, ["/usr/sbin/xfs_growfs", partition])
    else:
        results["fs_resize"] = {"success": False, "stderr": f"unsupported fs type: {fs_type}"}

    return {"success": all(v.get("success", False) for v in results.values()), "details": results}


def extend_disk(vm_id: str, disk_target: str, new_size_gb: int) -> dict:
    disks = get_disk_info(vm_id)
    current_disk = next((d for d in disks if d["target"] == disk_target), None)
    if current_disk is None:
        return {
            "success": False,
            "old_size_gb": None,
            "new_size_gb": new_size_gb,
            "guest_resize_attempted": False,
            "message": f"Disk target '{disk_target}' not found on VM '{vm_id}'",
        }

    old_size_gb = current_disk["capacity_gb"] or 0
    if new_size_gb <= old_size_gb:
        return {
            "success": False,
            "old_size_gb": old_size_gb,
            "new_size_gb": new_size_gb,
            "guest_resize_attempted": False,
            "message": f"new_size_gb ({new_size_gb}) must exceed current size ({old_size_gb} GB)",
        }

    new_size_bytes = new_size_gb * _GB
    try:
        _run(["virsh", "blockresize", vm_id, disk_target, str(new_size_bytes)], timeout=30)
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "old_size_gb": old_size_gb,
            "new_size_gb": new_size_gb,
            "guest_resize_attempted": False,
            "message": f"blockresize failed: {e.stderr.strip()}",
        }
    except Exception as e:
        return {
            "success": False,
            "old_size_gb": old_size_gb,
            "new_size_gb": new_size_gb,
            "guest_resize_attempted": False,
            "message": str(e),
        }

    guest_resize_attempted = False
    guest_resize_result = None
    if check_guest_agent(vm_id):
        guest_resize_attempted = True
        guest_resize_result = resize_guest_fs(vm_id)

    return {
        "success": True,
        "old_size_gb": old_size_gb,
        "new_size_gb": new_size_gb,
        "guest_resize_attempted": guest_resize_attempted,
        "guest_resize_result": guest_resize_result,
        "message": (
            f"Disk {disk_target} extended from {old_size_gb} GB to {new_size_gb} GB. "
            + ("Guest FS resize attempted." if guest_resize_attempted
               else "Guest agent unavailable; manual resize may be needed.")
        ),
    }






