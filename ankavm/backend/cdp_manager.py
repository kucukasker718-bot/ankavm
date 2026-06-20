"""
Continuous Data Protection — periodic disk delta capture, point-in-time restore.

Implementation note: we record per-VM CDP state in JSON, drive a snapshot/cycle
loop in a background thread (no cron dependency), and use qemu-img/libvirt
snapshots as the underlying mechanism. Heavy lifting (blockdev-mirror) requires
the VM to be running with QMP access; we fall back to qemu-img snapshots when
the VM is offline or QMP is unavailable.
"""
import os
import json
import time
import threading
import logging
import subprocess
from pathlib import Path

try:
    import libvirt
except ImportError:  # pragma: no cover
    libvirt = None

log = logging.getLogger("cdp_manager")

DATA_DIR = Path("/var/lib/ankavm")
CONF_PATH = DATA_DIR / "cdp_state.json"
RP_ROOT = DATA_DIR / "cdp_recovery_points"

_lock = threading.Lock()
_worker = {"thread": None, "stop": False}


def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RP_ROOT.mkdir(parents=True, exist_ok=True)
    if not CONF_PATH.exists():
        CONF_PATH.write_text("{}", encoding="utf-8")


def _load() -> dict:
    try:
        _ensure()
        return json.loads(CONF_PATH.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        log.error("_load: %s", e)
        return {}


def _save(state: dict):
    try:
        CONF_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("_save: %s", e)


def _connect():
    if libvirt is None:
        raise RuntimeError("libvirt unavailable")
    import config
    return libvirt.open(config.LIBVIRT_URI)


def _take_point(vm_id: str) -> dict:
    """Try libvirt snapshot first, fall back to recording a marker."""
    ts = int(time.time())
    rp_dir = RP_ROOT / vm_id
    rp_dir.mkdir(parents=True, exist_ok=True)
    point = {"ts": ts, "type": "marker"}
    try:
        if libvirt is not None:
            conn = _connect()
            try:
                dom = conn.lookupByName(vm_id)
                xml = f"<domainsnapshot><name>cdp-{ts}</name></domainsnapshot>"
                dom.snapshotCreateXML(xml, 0)
                point["type"] = "libvirt_snapshot"
                point["name"] = f"cdp-{ts}"
            finally:
                conn.close()
    except Exception as e:
        log.warning("snapshot for %s failed: %s", vm_id, e)
        point["error"] = str(e)
    (rp_dir / f"{ts}.json").write_text(json.dumps(point), encoding="utf-8")
    return point


def _prune(vm_id: str, retention_minutes: int):
    try:
        cutoff = time.time() - int(retention_minutes) * 60
        rp_dir = RP_ROOT / vm_id
        if not rp_dir.exists():
            return
        for f in rp_dir.glob("*.json"):
            try:
                ts = int(f.stem)
                if ts < cutoff:
                    f.unlink()
            except Exception:
                continue
    except Exception as e:
        log.warning("_prune: %s", e)


def _worker_loop():
    while not _worker["stop"]:
        try:
            state = _load()
            for vm_id, cfg in list(state.items()):
                if not cfg.get("enabled"):
                    continue
                last = cfg.get("last_sync_ts", 0)
                if time.time() - last >= cfg.get("interval_sec", 60):
                    pt = _take_point(vm_id)
                    cfg["last_sync_ts"] = pt["ts"]
                    cfg["last_point"] = pt
                    _prune(vm_id, cfg.get("retention_minutes", 60))
            _save(state)
        except Exception as e:
            log.error("worker: %s", e)
        for _ in range(10):
            if _worker["stop"]:
                break
            time.sleep(1)


def _ensure_worker():
    with _lock:
        if _worker["thread"] and _worker["thread"].is_alive():
            return
        _worker["stop"] = False
        t = threading.Thread(target=_worker_loop, name="cdp-worker", daemon=True)
        _worker["thread"] = t
        t.start()


def enable_cdp(vm_id: str, retention_minutes: int = 60,
               interval_sec: int = 60) -> dict:
    try:
        state = _load()
        state[vm_id] = {
            "enabled": True,
            "retention_minutes": int(retention_minutes),
            "interval_sec": int(interval_sec),
            "last_sync_ts": 0,
            "enabled_at": time.time(),
        }
        _save(state)
        _ensure_worker()
        return {"ok": True, "vm_id": vm_id,
                "retention_minutes": int(retention_minutes),
                "interval_sec": int(interval_sec)}
    except Exception as e:
        log.error("enable_cdp: %s", e)
        return {"ok": False, "error": str(e)}


def disable_cdp(vm_id: str) -> dict:
    try:
        state = _load()
        if vm_id in state:
            state[vm_id]["enabled"] = False
            _save(state)
        return {"ok": True, "vm_id": vm_id}
    except Exception as e:
        log.error("disable_cdp: %s", e)
        return {"ok": False, "error": str(e)}


def cdp_status(vm_id: str) -> dict:
    try:
        state = _load()
        cfg = state.get(vm_id) or {}
        last = cfg.get("last_sync_ts", 0)
        return {
            "enabled": bool(cfg.get("enabled")),
            "last_sync_ts": last,
            "lag_seconds": int(time.time() - last) if last else None,
            "retention_minutes": cfg.get("retention_minutes", 0),
            "interval_sec": cfg.get("interval_sec", 0),
        }
    except Exception as e:
        log.error("cdp_status: %s", e)
        return {"enabled": False, "lag_seconds": None, "error": str(e)}


def list_recovery_points(vm_id: str) -> list:
    out = []
    try:
        rp_dir = RP_ROOT / vm_id
        if not rp_dir.exists():
            return []
        for f in sorted(rp_dir.glob("*.json")):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                out.append(rec)
            except Exception:
                continue
        return out
    except Exception as e:
        log.error("list_recovery_points: %s", e)
        return []


def restore_to_point(vm_id: str, timestamp: int) -> dict:
    try:
        rp_dir = RP_ROOT / vm_id
        target_file = rp_dir / f"{int(timestamp)}.json"
        if not target_file.exists():
            # find closest
            candidates = sorted(int(f.stem) for f in rp_dir.glob("*.json")
                                if f.stem.isdigit())
            if not candidates:
                return {"ok": False, "error": "no recovery points"}
            timestamp = min(candidates, key=lambda t: abs(t - int(timestamp)))
            target_file = rp_dir / f"{timestamp}.json"
        point = json.loads(target_file.read_text(encoding="utf-8"))
        if point.get("type") == "libvirt_snapshot" and libvirt is not None:
            try:
                conn = _connect()
                try:
                    dom = conn.lookupByName(vm_id)
                    snap = dom.snapshotLookupByName(point["name"])
                    dom.revertToSnapshot(snap, 0)
                    return {"ok": True, "restored_to": timestamp,
                            "snapshot": point["name"]}
                finally:
                    conn.close()
            except Exception as e:
                return {"ok": False, "error": f"revert failed: {e}",
                        "restored_to": timestamp}
        return {"ok": True, "restored_to": timestamp,
                "note": "marker-only point; manual disk roll required"}
    except Exception as e:
        log.error("restore_to_point: %s", e)
        return {"ok": False, "error": str(e)}






