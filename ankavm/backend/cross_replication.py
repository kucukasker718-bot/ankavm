"""
ankavm Cross-Site Replication â€” v2.5.7
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
VM disk'lerini uzak host'a rsync / qemu-img+ssh ile Ã§oÄŸalt.
Async mod: manuel-trigger thread (AUTO-START JOB YOK).

API:
    configure_replication(vm_id, config) -> dict
    get_replication(vm_id) -> dict | None
    list_replications() -> list
    run_replication(vm_id) -> dict
    get_replication_status(vm_id) -> dict  {lag, RPO}
    promote_replica(vm_id) -> dict  (stub + warning)

Persistent state: /var/lib/ankavm/cross_replication.json
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

log = logging.getLogger("cross_replication")

_DATA_FILE = Path("/var/lib/ankavm/cross_replication.json")
_lock      = threading.Lock()


# â”€â”€ I/O helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("load fail: %s", e)
    return {}


def _save(data: dict):
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_DATA_FILE)
    except Exception as e:
        log.warning("save fail: %s", e)


# â”€â”€ Replication engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _find_disk_images(vm_id: str, cfg: dict) -> list:
    """
    Attempt to locate disk images for the VM.
    Checks common locations; falls back to an empty list with a warning.
    """
    search_dirs = [
        "/var/lib/libvirt/images",
        "/var/lib/ankavm/images",
        f"/var/lib/ankavm/vms/{vm_id}",
    ]
    images = []
    for d in search_dirs:
        dp = Path(d)
        if not dp.exists():
            continue
        for ext in (".qcow2", ".img", ".raw"):
            for f in dp.iterdir():
                if f.is_file() and vm_id in f.name and f.suffix == ext:
                    images.append(str(f))
    if not images:
        log.warning("disk image bulunamadÄ± vm=%s", vm_id)
    return images


def _ssh_opts(cfg: dict) -> list:
    """Build SSH options list from config."""
    opts = ["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
    key = cfg.get("ssh_key_path", "")
    if key:
        opts += ["-i", key]
    return opts


def _rsync_replicate(image: str, cfg: dict) -> dict:
    """rsync a single image to remote."""
    host    = cfg.get("target_host", "")
    user    = cfg.get("target_user", "root")
    dst_dir = cfg.get("target_path", "/var/lib/libvirt/images")
    if not host:
        return {"ok": False, "error": "target_host tanÄ±msÄ±z"}
    ssh_opts = " ".join(_ssh_opts(cfg))
    cmd = [
        "rsync", "-az", "--inplace", "--partial",
        "-e", f"ssh {ssh_opts}",
        image,
        f"{user}@{host}:{dst_dir}/",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()[:400]}
        return {"ok": True, "method": "rsync", "image": image}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "rsync timeout (30 dk)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _qemu_img_replicate(image: str, cfg: dict) -> dict:
    """
    qemu-img convert + ssh copy (incremental not available without dirty bitmap).
    Uses rsync as the transport for qcow2 â€” acts as incremental via --inplace.
    """
    return _rsync_replicate(image, cfg)


def _do_replicate(vm_id: str, cfg: dict) -> dict:
    images  = _find_disk_images(vm_id, cfg)
    method  = cfg.get("mode", "rsync")
    results = []
    ok_count = 0
    for img in images:
        if method == "rsync":
            r = _rsync_replicate(img, cfg)
        else:
            r = _qemu_img_replicate(img, cfg)
        results.append(r)
        if r.get("ok"):
            ok_count += 1
    return {
        "ok":        ok_count == len(images) and len(images) > 0,
        "images":    len(images),
        "succeeded": ok_count,
        "results":   results,
    }


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def configure_replication(vm_id: str, config: dict) -> dict:
    """
    config keys:
      target_host   str   â€” remote host IP/FQDN
      target_user   str   â€” SSH user (default root)
      target_path   str   â€” remote destination directory
      mode          str   â€” 'rsync' | 'qemu-img' (default rsync)
      interval_min  int   â€” for manual-trigger reference only (NO auto-start)
      ssh_key_path  str   â€” private key for SSH
    """
    if not vm_id:
        return {"ok": False, "error": "vm_id zorunlu"}
    if not config.get("target_host"):
        return {"ok": False, "error": "target_host zorunlu"}
    with _lock:
        data = _load()
        data[vm_id] = {
            "vm_id":        vm_id,
            "target_host":  config.get("target_host", ""),
            "target_user":  config.get("target_user", "root"),
            "target_path":  config.get("target_path", "/var/lib/libvirt/images"),
            "mode":         config.get("mode", "rsync"),
            "interval_min": int(config.get("interval_min") or 60),
            "ssh_key_path": config.get("ssh_key_path", ""),
            "updated":      int(time.time()),
            "last_run":     None,
            "status":       "configured",
        }
        _save(data)
    log.info("replication configured vm=%s target=%s", vm_id, config.get("target_host"))
    return {"ok": True, "vm_id": vm_id}


def get_replication(vm_id: str) -> Optional[dict]:
    with _lock:
        data = _load()
    return data.get(vm_id)


def list_replications() -> list:
    with _lock:
        data = _load()
    return list(data.values())


def run_replication(vm_id: str) -> dict:
    """
    Trigger replication manually. Runs in foreground (caller may wrap in thread).
    NO automatic periodic scheduling.
    """
    cfg = get_replication(vm_id)
    if not cfg:
        return {"ok": False, "error": f"replication config yok: {vm_id}"}

    run_id = str(uuid.uuid4())[:8]
    ts_start = int(time.time())

    with _lock:
        data = _load()
        if vm_id in data:
            data[vm_id]["status"] = "running"
            _save(data)

    try:
        detail = _do_replicate(vm_id, cfg)
    except Exception as e:
        detail = {"ok": False, "error": str(e)}

    ts_end = int(time.time())
    elapsed = ts_end - ts_start

    run_record = {
        "run_id":  run_id,
        "ts":      ts_start,
        "elapsed": elapsed,
        **detail,
    }

    with _lock:
        data = _load()
        if vm_id in data:
            data[vm_id]["last_run"] = run_record
            data[vm_id]["status"]   = "ok" if detail.get("ok") else "error"
            data[vm_id]["last_ts"]  = ts_end
            _save(data)

    log.info("replication run=%s vm=%s ok=%s elapsed=%ds",
             run_id, vm_id, detail.get("ok"), elapsed)
    return run_record


def run_replication_async(vm_id: str) -> dict:
    """
    Run replication in a background thread.
    Returns immediately with run_id. Does NOT auto-start; caller decides.
    """
    run_id = str(uuid.uuid4())[:8]

    def _worker():
        run_replication(vm_id)

    t = threading.Thread(target=_worker, daemon=True, name=f"repl-{vm_id[:8]}")
    t.start()
    return {"ok": True, "run_id": run_id, "async": True,
            "note": "Arka planda Ã§alÄ±ÅŸÄ±yor â€” /status ile kontrol et"}


def get_replication_status(vm_id: str) -> dict:
    """
    Return replication lag and RPO estimate.
    lag = seconds since last successful run.
    RPO = configured interval_min (maximum tolerable data loss window).
    """
    cfg = get_replication(vm_id)
    if not cfg:
        return {"vm_id": vm_id, "configured": False}
    last_run = cfg.get("last_run") or {}
    last_ts  = cfg.get("last_ts")
    lag_sec  = (int(time.time()) - last_ts) if last_ts else None
    return {
        "vm_id":        vm_id,
        "configured":   True,
        "status":       cfg.get("status", "unknown"),
        "lag_sec":      lag_sec,
        "lag_human":    _fmt_lag(lag_sec),
        "RPO_min":      cfg.get("interval_min", 60),
        "last_run":     last_run,
        "target_host":  cfg.get("target_host"),
        "mode":         cfg.get("mode", "rsync"),
    }


def _fmt_lag(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def promote_replica(vm_id: str) -> dict:
    """
    STUB â€” Promote replica to primary.
    WARNING: This requires manual DNS/IP failover and VM reconfiguration.
    Returns a warning with required steps; does NOT perform promotion automatically.
    """
    cfg = get_replication(vm_id)
    if not cfg:
        return {"ok": False, "error": f"replication config yok: {vm_id}"}
    log.warning("promote_replica STUB called vm=%s â€” manual steps required", vm_id)
    return {
        "ok":      False,
        "stub":    True,
        "warning": (
            "promote_replica henÃ¼z otomatik uygulanmadÄ±. "
            "Manuel adÄ±mlar: "
            "1) Hedef VM'yi baÅŸlat, "
            "2) DNS/VIP'i gÃ¼ncelle, "
            "3) Kaynak VM'yi kapat veya izole et, "
            "4) Replikasyonu ters yÃ¶nde yeniden yapÄ±landÄ±r."
        ),
        "vm_id":       vm_id,
        "target_host": cfg.get("target_host"),
    }






