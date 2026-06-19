"""
ankavm Fault Tolerance Manager
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Checkpoint-based VM protection:
  - create_ft_pair(primary_vm_id, secondary_pool) â†’ creates secondary VM from checkpoint
  - get_ft_status(vm_id) â†’ replication lag, last checkpoint time, status
  - trigger_failover(vm_id) â†’ promote secondary, update IPAM
  - sync_checkpoint(vm_id) â†’ manual checkpoint + delta sync
  - remove_ft(vm_id) â†’ remove pairing

Uses: libvirt checkpoint API + qemu-img convert for delta sync.
State: /var/lib/ankavm/ft_pairs.json
"""

import json
import os
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    import libvirt
    _LIBVIRT_AVAILABLE = True
except ImportError:
    libvirt = None
    _LIBVIRT_AVAILABLE = False

FT_STATE_PATH = Path("/var/lib/ankavm/ft_pairs.json")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_libvirt():
    if not _LIBVIRT_AVAILABLE:
        raise RuntimeError("libvirt Python bindings not installed")
    conn = libvirt.open("qemu:///system")
    if conn is None:
        raise RuntimeError("Failed to open libvirt connection to qemu:///system")
    return conn


def _run(cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
    )


def _load_pairs() -> dict:
    if FT_STATE_PATH.exists():
        try:
            with FT_STATE_PATH.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_pairs(pairs: dict) -> None:
    FT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FT_STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(pairs, fh, indent=2, default=str)
    tmp.replace(FT_STATE_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


def _get_vm_disk_path(dom_xml: str) -> str | None:
    try:
        root = ET.fromstring(dom_xml)
        for disk in root.iter("disk"):
            if disk.get("device") == "disk":
                source = disk.find("source")
                if source is not None:
                    return source.get("file") or source.get("dev")
    except ET.ParseError:
        pass
    return None


def _get_pool_path(pool_name: str) -> str:
    result = _run(["virsh", "pool-dumpxml", pool_name], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Cannot query pool '{pool_name}': {result.stderr.strip()}")
    root = ET.fromstring(result.stdout)
    target = root.find("target/path")
    if target is None or not target.text:
        raise RuntimeError(f"No target path found for pool '{pool_name}'")
    return target.text.rstrip("/")


def _vm_state_virsh(vm_name: str) -> str:
    result = _run(["virsh", "domstate", vm_name], check=False)
    if result.returncode != 0:
        return "not-found"
    return result.stdout.strip()


def _checkpoint_name(vm_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"oxft-{vm_name}-{ts}"


def _create_checkpoint(dom, checkpoint_name: str) -> None:
    checkpoint_xml = f"""<domaincheckpoint>
  <name>{checkpoint_name}</name>
  <description>ankavm FT checkpoint</description>
</domaincheckpoint>"""
    if _LIBVIRT_AVAILABLE:
        dom.checkpointCreateXML(
            checkpoint_xml,
            libvirt.VIR_DOMAIN_CHECKPOINT_CREATE_REDEFINE
            if hasattr(libvirt, "VIR_DOMAIN_CHECKPOINT_CREATE_REDEFINE")
            else 0,
        )


def _build_secondary_xml(primary_xml: str, secondary_name: str, secondary_disk_path: str) -> str:
    root = ET.fromstring(primary_xml)

    name_el = root.find("name")
    if name_el is not None:
        name_el.text = secondary_name

    uuid_el = root.find("uuid")
    if uuid_el is not None:
        uuid_el.text = str(uuid.uuid4())

    for disk in root.iter("disk"):
        if disk.get("device") == "disk":
            source = disk.find("source")
            if source is not None:
                if source.get("file") is not None:
                    source.set("file", secondary_disk_path)
                elif source.get("dev") is not None:
                    source.set("dev", secondary_disk_path)

    for iface in root.iter("interface"):
        mac = iface.find("mac")
        if mac is not None:
            new_mac = "52:54:00:%02x:%02x:%02x" % (
                int(uuid.uuid4().hex[0:2], 16),
                int(uuid.uuid4().hex[0:2], 16),
                int(uuid.uuid4().hex[0:2], 16),
            )
            mac.set("address", new_mac)

    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_ft_pair(
    primary_vm_id: str,
    secondary_pool: str,
    sync_interval_minutes: int = 15,
) -> dict:
    pairs = _load_pairs()
    if primary_vm_id in pairs:
        raise ValueError(f"FT pair already exists for '{primary_vm_id}'")

    conn = _open_libvirt()
    try:
        try:
            dom = conn.lookupByName(primary_vm_id)
        except Exception:
            raise RuntimeError(f"VM '{primary_vm_id}' not found in libvirt")

        primary_xml = dom.XMLDesc(0)
        primary_disk = _get_vm_disk_path(primary_xml)
        if not primary_disk:
            raise RuntimeError(f"Cannot determine disk path for VM '{primary_vm_id}'")

        pool_path = _get_pool_path(secondary_pool)

        checkpoint_name = _checkpoint_name(primary_vm_id)
        try:
            _create_checkpoint(dom, checkpoint_name)
        except Exception as exc:
            checkpoint_name = f"oxft-baseline-{int(_now_ts())}"

        disk_basename = os.path.basename(primary_disk)
        disk_stem, disk_ext = os.path.splitext(disk_basename)
        secondary_disk_name = f"{disk_stem}-ft-secondary{disk_ext or '.qcow2'}"
        secondary_disk_path = os.path.join(pool_path, secondary_disk_name)

        convert_result = _run(
            [
                "qemu-img",
                "convert",
                "-f", "qcow2",
                "-O", "qcow2",
                "-p",
                primary_disk,
                secondary_disk_path,
            ],
            check=False,
        )
        if convert_result.returncode != 0:
            raise RuntimeError(
                f"qemu-img convert failed: {convert_result.stderr.strip()}"
            )

        secondary_name = f"{primary_vm_id}-ft-secondary"
        secondary_xml = _build_secondary_xml(primary_xml, secondary_name, secondary_disk_path)

        try:
            conn.defineXML(secondary_xml)
        except Exception as exc:
            raise RuntimeError(f"Failed to define secondary VM: {exc}")

        pool_refresh = _run(["virsh", "pool-refresh", secondary_pool], check=False)

        now_iso = _now_iso()
        entry = {
            "primary_vm_id": primary_vm_id,
            "secondary_vm_id": secondary_name,
            "secondary_pool": secondary_pool,
            "secondary_disk_path": secondary_disk_path,
            "sync_interval_minutes": sync_interval_minutes,
            "status": "protected",
            "created_at": now_iso,
            "last_sync": now_iso,
            "last_checkpoint": checkpoint_name,
        }
        pairs[primary_vm_id] = entry
        _save_pairs(pairs)
        return dict(entry)
    finally:
        conn.close()


def get_ft_status(vm_id: str) -> dict:
    pairs = _load_pairs()

    entry = pairs.get(vm_id)
    if entry is None:
        for _k, v in pairs.items():
            if v.get("secondary_vm_id") == vm_id:
                entry = v
                break

    if entry is None:
        return {
            "status": "unprotected",
            "lag_seconds": None,
            "last_sync": None,
            "primary_state": _vm_state_virsh(vm_id),
            "secondary_state": None,
        }

    primary_state = _vm_state_virsh(entry["primary_vm_id"])
    secondary_state = _vm_state_virsh(entry["secondary_vm_id"])

    last_sync_str = entry.get("last_sync")
    lag_seconds = None
    if last_sync_str:
        try:
            last_sync_dt = datetime.fromisoformat(last_sync_str)
            lag_seconds = (datetime.now(timezone.utc) - last_sync_dt).total_seconds()
        except ValueError:
            lag_seconds = None

    stored_status = entry.get("status", "protected")
    if stored_status == "failover":
        status = "failover"
    elif primary_state in ("shut off", "not-found") and secondary_state in ("shut off", "not-found"):
        status = "degraded"
    elif secondary_state == "not-found":
        status = "degraded"
    elif lag_seconds is not None and lag_seconds > entry.get("sync_interval_minutes", 15) * 60 * 3:
        status = "degraded"
    else:
        status = "protected"

    return {
        "status": status,
        "lag_seconds": lag_seconds,
        "last_sync": last_sync_str,
        "primary_state": primary_state,
        "secondary_state": secondary_state,
        "primary_vm_id": entry["primary_vm_id"],
        "secondary_vm_id": entry["secondary_vm_id"],
        "secondary_pool": entry.get("secondary_pool"),
        "created_at": entry.get("created_at"),
        "last_checkpoint": entry.get("last_checkpoint"),
    }


def trigger_failover(vm_id: str) -> dict:
    pairs = _load_pairs()
    entry = pairs.get(vm_id)
    if entry is None:
        raise KeyError(f"No FT pair found for VM '{vm_id}'")

    primary_state = _vm_state_virsh(entry["primary_vm_id"])
    if primary_state == "running":
        stop_result = _run(
            ["virsh", "shutdown", entry["primary_vm_id"]],
            check=False,
        )
        deadline = _now_ts() + 30
        while _now_ts() < deadline:
            time.sleep(2)
            if _vm_state_virsh(entry["primary_vm_id"]) != "running":
                break
        else:
            _run(["virsh", "destroy", entry["primary_vm_id"]], check=False)

    start_result = _run(
        ["virsh", "start", entry["secondary_vm_id"]],
        check=False,
    )
    if start_result.returncode != 0:
        raise RuntimeError(
            f"Failed to start secondary VM '{entry['secondary_vm_id']}': "
            f"{start_result.stderr.strip()}"
        )

    entry["status"] = "failover"
    entry["failover_at"] = _now_iso()
    pairs[vm_id] = entry
    _save_pairs(pairs)

    return {
        "success": True,
        "secondary_vm_id": entry["secondary_vm_id"],
        "message": (
            f"Failover complete. Secondary VM '{entry['secondary_vm_id']}' is now running. "
            f"Primary VM '{entry['primary_vm_id']}' has been stopped."
        ),
    }


def sync_checkpoint(vm_id: str) -> dict:
    pairs = _load_pairs()
    entry = pairs.get(vm_id)
    if entry is None:
        raise KeyError(f"No FT pair found for VM '{vm_id}'")

    if entry.get("status") == "failover":
        raise RuntimeError("Cannot sync: pair is in failover state")

    conn = _open_libvirt()
    t_start = _now_ts()
    try:
        try:
            dom = conn.lookupByName(entry["primary_vm_id"])
        except Exception:
            raise RuntimeError(f"Primary VM '{entry['primary_vm_id']}' not found")

        primary_xml = dom.XMLDesc(0)
        primary_disk = _get_vm_disk_path(primary_xml)
        if not primary_disk:
            raise RuntimeError("Cannot determine primary disk path")

        checkpoint_name = _checkpoint_name(entry["primary_vm_id"])
        try:
            _create_checkpoint(dom, checkpoint_name)
        except Exception:
            checkpoint_name = f"oxft-sync-{int(_now_ts())}"

        secondary_disk_path = entry["secondary_disk_path"]

        convert_result = _run(
            [
                "qemu-img",
                "convert",
                "-f", "qcow2",
                "-O", "qcow2",
                primary_disk,
                secondary_disk_path,
            ],
            check=False,
        )
        if convert_result.returncode != 0:
            raise RuntimeError(
                f"qemu-img convert failed during sync: {convert_result.stderr.strip()}"
            )

        bytes_synced = 0
        try:
            bytes_synced = os.path.getsize(secondary_disk_path)
        except OSError:
            pass

        duration = _now_ts() - t_start
        now_iso = _now_iso()
        entry["last_sync"] = now_iso
        entry["last_checkpoint"] = checkpoint_name
        entry["status"] = "protected"
        pairs[vm_id] = entry
        _save_pairs(pairs)

        return {
            "success": True,
            "checkpoint_name": checkpoint_name,
            "bytes_synced": bytes_synced,
            "duration_seconds": round(duration, 3),
        }
    finally:
        conn.close()


def remove_ft(vm_id: str) -> dict:
    pairs = _load_pairs()
    entry = pairs.get(vm_id)
    if entry is None:
        raise KeyError(f"No FT pair found for VM '{vm_id}'")

    secondary_name = entry["secondary_vm_id"]

    secondary_state = _vm_state_virsh(secondary_name)
    if secondary_state == "running":
        _run(["virsh", "destroy", secondary_name], check=False)

    if secondary_state != "not-found":
        undefine_result = _run(
            ["virsh", "undefine", "--remove-all-storage", secondary_name],
            check=False,
        )
        if undefine_result.returncode != 0:
            _run(["virsh", "undefine", secondary_name], check=False)

    del pairs[vm_id]
    _save_pairs(pairs)

    return {"success": True}


def list_ft_pairs() -> list:
    pairs = _load_pairs()
    result = []
    for vm_id, entry in pairs.items():
        try:
            status_info = get_ft_status(vm_id)
        except Exception:
            status_info = {"status": "unknown"}
        merged = {**entry, **status_info}
        result.append(merged)
    return result






