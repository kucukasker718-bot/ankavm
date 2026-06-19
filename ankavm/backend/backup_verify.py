"""
ankavm Backup Verification â€” v2.5.7
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
mount veya boot test ile backup bÃ¼tÃ¼nlÃ¼ÄŸÃ¼nÃ¼ doÄŸrula.

API:
    verify_backup(backup_path, mode='mount'|'boot') -> dict
    list_verifications(limit=50) -> list

Modes:
    mount â€” qemu-nbd ile baÄŸla, fsck / dosya kontrol, unmount
    boot  â€” geÃ§ici isolated libvirt VM, 60 s timeout, agent ping, destroy+undefine

Log: /var/log/ankavm/backup_verify.jsonl
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("backup_verify")

_LOG_FILE = Path("/var/log/ankavm/backup_verify.jsonl")
_lock     = threading.Lock()

# libvirt optional (boot mode)
try:
    import libvirt as _libvirt
    _LIBVIRT_OK = True
except ImportError:
    _libvirt = None
    _LIBVIRT_OK = False


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _log_result(result: dict):
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("log_result fail: %s", e)


def _check_qemu_nbd() -> bool:
    try:
        r = subprocess.run(["which", "qemu-nbd"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _nbd_connect(image_path: str, dev: str) -> bool:
    try:
        # Load nbd module
        subprocess.run(["modprobe", "nbd", "max_part=8"],
                       capture_output=True, timeout=10)
        r = subprocess.run(
            ["qemu-nbd", "--connect", dev, image_path],
            capture_output=True, timeout=30
        )
        return r.returncode == 0
    except Exception as e:
        log.warning("nbd_connect fail: %s", e)
        return False


def _nbd_disconnect(dev: str):
    try:
        subprocess.run(["qemu-nbd", "--disconnect", dev],
                       capture_output=True, timeout=15)
    except Exception:
        pass


def _fsck_partition(part: str) -> dict:
    try:
        r = subprocess.run(
            ["fsck", "-n", part],
            capture_output=True, text=True, timeout=120
        )
        ok = r.returncode in (0, 1)  # 0=clean, 1=corrected (read-only so won't happen)
        return {"partition": part, "ok": ok, "stdout": r.stdout.strip()[:500]}
    except subprocess.TimeoutExpired:
        return {"partition": part, "ok": False, "error": "fsck timeout"}
    except Exception as e:
        return {"partition": part, "ok": False, "error": str(e)}


# â”€â”€ mount mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _verify_mount(backup_path: str, verify_id: str) -> dict:
    if not _check_qemu_nbd():
        return {
            "ok":    False,
            "mode":  "mount",
            "error": "qemu-nbd bulunamadÄ± â€” 'apt install qemu-utils' gerekli",
        }

    dev = "/dev/nbd0"
    mount_pt = f"/tmp/ankavm_verify_{verify_id}"
    result: dict = {"mode": "mount", "dev": dev}

    connected = _nbd_connect(backup_path, dev)
    if not connected:
        return {"ok": False, "mode": "mount", "error": f"qemu-nbd connect baÅŸarÄ±sÄ±z: {dev}"}

    try:
        time.sleep(1)  # let kernel enumerate partitions

        # Detect partitions
        lsblk = subprocess.run(
            ["lsblk", "-J", dev], capture_output=True, text=True, timeout=10
        )
        partitions = []
        try:
            blk = json.loads(lsblk.stdout)
            children = blk.get("blockdevices", [{}])[0].get("children") or []
            partitions = [f"/dev/{c['name']}" for c in children if c.get("name")]
        except Exception:
            partitions = [f"{dev}p1"]

        # fsck each partition (read-only)
        fsck_results = [_fsck_partition(p) for p in partitions[:4]]
        result["partitions"] = fsck_results
        result["fsck_ok"] = all(r.get("ok") for r in fsck_results)

        # Try mounting root partition
        os.makedirs(mount_pt, exist_ok=True)
        mounted = False
        for p in partitions:
            r = subprocess.run(
                ["mount", "-o", "ro", p, mount_pt],
                capture_output=True, timeout=15
            )
            if r.returncode == 0:
                mounted = True
                result["mounted_partition"] = p
                # Quick sanity: count top-level files
                try:
                    items = os.listdir(mount_pt)
                    result["root_items"] = len(items)
                    result["has_etc"]    = "etc" in items
                    result["has_boot"]   = "boot" in items or "grub" in items
                except Exception:
                    pass
                subprocess.run(["umount", mount_pt], capture_output=True, timeout=15)
                break
        result["mount_ok"] = mounted
        try:
            os.rmdir(mount_pt)
        except Exception:
            pass

        result["ok"] = result.get("fsck_ok", False) or result.get("mount_ok", False)

    finally:
        _nbd_disconnect(dev)

    return result


# â”€â”€ boot mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _verify_boot(backup_path: str, verify_id: str) -> dict:
    if not _LIBVIRT_OK:
        return {"ok": False, "mode": "boot", "error": "libvirt kurulu deÄŸil"}

    vm_name = f"ankavm-verify-{verify_id}"
    boot_xml = f"""<domain type='qemu'>
  <name>{vm_name}</name>
  <memory unit='MiB'>512</memory>
  <vcpu>1</vcpu>
  <os><type arch='x86_64'>hvm</type><boot dev='hd'/></os>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='{backup_path}'/>
      <target dev='vda' bus='virtio'/>
      <readonly/>
    </disk>
    <interface type='user'>
      <model type='virtio'/>
    </interface>
    <channel type='unix'>
      <target type='virtio' name='org.qemu.guest_agent.0'/>
    </channel>
  </devices>
  <features><acpi/><apic/></features>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>destroy</on_reboot>
  <on_crash>destroy</on_crash>
</domain>"""

    result: dict = {"mode": "boot", "vm_name": vm_name}
    conn = None
    domain = None
    try:
        conn = _libvirt.open("qemu:///system")
        domain = conn.defineXML(boot_xml)
        domain.create()
        result["started"] = True

        # Poll agent-ping up to 60 seconds
        deadline = time.time() + 60
        agent_ok = False
        while time.time() < deadline:
            try:
                resp = domain.qemuAgentCommand('{"execute":"guest-ping"}', 3, 0)
                if resp:
                    agent_ok = True
                    break
            except Exception:
                pass
            time.sleep(3)

        result["agent_responded"] = agent_ok
        result["ok"] = agent_ok

    except Exception as e:
        log.warning("boot_verify fail: %s", e)
        result["ok"]    = False
        result["error"] = str(e)
    finally:
        # Always destroy + undefine
        if domain:
            try:
                domain.destroy()
            except Exception:
                pass
            try:
                domain.undefine()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return result


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def verify_backup(backup_path: str, mode: str = "mount") -> dict:
    """
    Verify a backup file.
    mode='mount': qemu-nbd mount + fsck (no VM needed)
    mode='boot':  boot isolated VM + agent-ping, then destroy
    """
    if not backup_path:
        return {"ok": False, "error": "backup_path zorunlu"}
    if not Path(backup_path).exists():
        return {"ok": False, "error": f"Dosya bulunamadÄ±: {backup_path}"}
    if mode not in ("mount", "boot"):
        return {"ok": False, "error": "mode 'mount' veya 'boot' olmalÄ±"}

    verify_id = str(uuid.uuid4())[:8]
    ts = int(time.time())

    if mode == "mount":
        detail = _verify_mount(backup_path, verify_id)
    else:
        detail = _verify_boot(backup_path, verify_id)

    record = {
        "verify_id":    verify_id,
        "ts":           ts,
        "backup_path":  backup_path,
        "mode":         mode,
        "ok":           detail.get("ok", False),
        "detail":       detail,
    }
    _log_result(record)
    log.info("verify id=%s path=%s mode=%s ok=%s",
             verify_id, backup_path, mode, record["ok"])
    return record


def list_verifications(limit: int = 50) -> list:
    """Return last N verification records."""
    try:
        if not _LOG_FILE.exists():
            return []
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-(limit):]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return list(reversed(out))
    except Exception as e:
        log.warning("list_verifications fail: %s", e)
        return []






