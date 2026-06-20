"""
ankavm 3-2-1 Backup — v2.5.7
──────────────────────────────
3 kopya / 2 farklı medya / 1 offsite.

API:
    set_321_policy(vm_id, policy) -> dict
    get_321_policy(vm_id) -> dict | None
    list_321_policies() -> list
    run_321_backup(vm_id) -> dict
    get_321_status(vm_id) -> dict  {copies, media_count, offsite, compliant}

Persistent state: /var/lib/ankavm/backup_321.json
"""

from __future__ import annotations
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("backup_321")

_DATA_FILE = Path("/var/lib/ankavm/backup_321.json")
_lock      = threading.Lock()

# Optional boto3 for S3/MinIO
try:
    import boto3
    from botocore.exceptions import ClientError as _BotoErr
    _BOTO3_OK = True
except ImportError:
    boto3    = None
    _BotoErr = Exception
    _BOTO3_OK = False


# ── I/O helpers ──────────────────────────────────────────────────────────────

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


# ── Offsite transfer helpers ──────────────────────────────────────────────────

def _copy_to_secondary(src: str, secondary_path: str) -> dict:
    """Local copy to secondary path."""
    try:
        dst_dir = Path(secondary_path)
        dst_dir.mkdir(parents=True, exist_ok=True)
        src_p   = Path(src)
        dst_p   = dst_dir / src_p.name
        shutil.copy2(src, str(dst_p))
        return {"ok": True, "path": str(dst_p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _offsite_s3(src: str, config: dict) -> dict:
    """Upload to S3/MinIO via boto3."""
    if not _BOTO3_OK:
        return {"ok": False, "error": "boto3 kurulu değil"}
    try:
        endpoint   = config.get("endpoint_url")
        bucket     = config.get("bucket", "ankavm-backups")
        access_key = config.get("access_key", "")
        secret_key = config.get("secret_key", "")
        region     = config.get("region", "us-east-1")
        src_p      = Path(src)
        key        = f"backup-321/{src_p.name}"
        kwargs = dict(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        s3 = boto3.client("s3", **kwargs)
        s3.upload_file(src, bucket, key)
        return {"ok": True, "bucket": bucket, "key": key}
    except _BotoErr as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _offsite_rsync(src: str, config: dict) -> dict:
    """rsync to remote host."""
    try:
        host   = config.get("host", "")
        user   = config.get("user", "root")
        path   = config.get("path", "/backup")
        port   = int(config.get("port", 22))
        key    = config.get("ssh_key_path", "")
        if not host:
            return {"ok": False, "error": "rsync host tanımsız"}
        cmd = ["rsync", "-az", "--progress"]
        if key:
            cmd += ["-e", f"ssh -p {port} -i {key} -o StrictHostKeyChecking=no"]
        else:
            cmd += ["-e", f"ssh -p {port} -o StrictHostKeyChecking=no"]
        cmd += [src, f"{user}@{host}:{path}/"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()[:400]}
        return {"ok": True, "host": host, "path": path}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "rsync timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _offsite_minio_mgr(src: str, config: dict):
    """Use minio_manager module if available."""
    try:
        import importlib
        mm = importlib.import_module("minio_manager")
        bucket = config.get("bucket", "ankavm-backups")
        key    = f"backup-321/{Path(src).name}"
        mm.upload_file(bucket, key, src)
        return {"ok": True, "bucket": bucket, "key": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Public API ────────────────────────────────────────────────────────────────

def set_321_policy(vm_id: str, policy: dict) -> dict:
    """
    policy keys:
      local_path      str   — primary backup directory
      secondary_path  str   — secondary local dir (2nd media)
      offsite         dict  — {type: s3|rsync|minio, config: {...}}
      retention       int   — keep N copies per location (default 7)
    """
    if not vm_id:
        return {"ok": False, "error": "vm_id zorunlu"}
    if not policy.get("local_path"):
        return {"ok": False, "error": "local_path zorunlu"}
    with _lock:
        data = _load()
        data[vm_id] = {
            "vm_id":          vm_id,
            "local_path":     policy.get("local_path", ""),
            "secondary_path": policy.get("secondary_path", ""),
            "offsite":        policy.get("offsite") or {},
            "retention":      int(policy.get("retention") or 7),
            "updated":        int(time.time()),
        }
        _save(data)
    log.info("321 policy set vm=%s", vm_id)
    return {"ok": True, "vm_id": vm_id}


def get_321_policy(vm_id: str) -> Optional[dict]:
    with _lock:
        data = _load()
    return data.get(vm_id)


def list_321_policies() -> list:
    with _lock:
        data = _load()
    return list(data.values())


def run_321_backup(vm_id: str) -> dict:
    """
    Execute 3-2-1 backup:
      1. Find the latest backup file in local_path for vm_id
      2. Copy to secondary_path (2nd media)
      3. Transfer to offsite

    Does NOT generate the backup itself (backup_scheduler handles that).
    Works with existing .qcow2 / .tar.gz / .img files.
    """
    policy = get_321_policy(vm_id)
    if not policy:
        return {"ok": False, "error": f"321 policy yok: {vm_id}"}

    local_path     = policy["local_path"]
    secondary_path = policy.get("secondary_path", "")
    offsite_cfg    = policy.get("offsite") or {}
    offsite_type   = offsite_cfg.get("type", "")
    retention      = int(policy.get("retention") or 7)

    run_id = str(uuid.uuid4())[:8]
    ts     = int(time.time())
    results: dict = {"run_id": run_id, "ts": ts, "vm_id": vm_id}

    # Find latest backup file
    try:
        lp = Path(local_path)
        if not lp.exists():
            return {"ok": False, "error": f"local_path bulunamadı: {local_path}"}
        candidates = sorted(
            [f for f in lp.iterdir()
             if f.is_file() and vm_id in f.name and
                f.suffix in (".qcow2", ".gz", ".img", ".raw", ".tar")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return {"ok": False, "error": f"Backup dosyası bulunamadı: {local_path}"}
        src_file = str(candidates[0])
        results["source"] = src_file
    except Exception as e:
        return {"ok": False, "error": f"Dosya tarama hatası: {e}"}

    copies_ok = 1  # local is copy #1
    media_set = {str(lp)}

    # Copy 2: secondary path
    if secondary_path:
        sec_result = _copy_to_secondary(src_file, secondary_path)
        results["secondary"] = sec_result
        if sec_result.get("ok"):
            copies_ok += 1
            media_set.add(str(Path(secondary_path)))
        # Retention on secondary
        _enforce_retention(secondary_path, vm_id, retention)
    else:
        results["secondary"] = {"ok": False, "error": "secondary_path tanımsız"}

    # Copy 3: offsite
    offsite_result: dict = {}
    if offsite_type == "s3":
        offsite_result = _offsite_s3(src_file, offsite_cfg.get("config") or {})
    elif offsite_type == "rsync":
        offsite_result = _offsite_rsync(src_file, offsite_cfg.get("config") or {})
    elif offsite_type == "minio":
        offsite_result = _offsite_minio_mgr(src_file, offsite_cfg.get("config") or {})
    else:
        offsite_result = {"ok": False, "error": "offsite type tanımsız (s3|rsync|minio)"}
    results["offsite"] = offsite_result
    if offsite_result.get("ok"):
        copies_ok += 1

    results["copies"]       = copies_ok
    results["media_count"]  = len(media_set)
    results["compliant"]    = (copies_ok >= 3 and len(media_set) >= 2 and offsite_result.get("ok"))
    results["ok"]           = copies_ok > 0

    # Retention on local
    _enforce_retention(local_path, vm_id, retention)

    # Persist status
    with _lock:
        data = _load()
        if vm_id in data:
            data[vm_id]["last_run"] = results
            _save(data)

    log.info("321 backup run=%s vm=%s copies=%d compliant=%s",
             run_id, vm_id, copies_ok, results["compliant"])
    return results


def _enforce_retention(directory: str, vm_id: str, keep: int):
    """Delete oldest backup files beyond retention limit."""
    try:
        dp = Path(directory)
        if not dp.exists():
            return
        files = sorted(
            [f for f in dp.iterdir()
             if f.is_file() and vm_id in f.name and
                f.suffix in (".qcow2", ".gz", ".img", ".raw", ".tar")],
            key=lambda x: x.stat().st_mtime,
        )
        to_delete = files[:-keep] if len(files) > keep else []
        for f in to_delete:
            try:
                f.unlink()
                log.debug("retention: silindi %s", f)
            except Exception:
                pass
    except Exception as e:
        log.warning("retention fail dir=%s: %s", directory, e)


def get_321_status(vm_id: str) -> dict:
    """Return 3-2-1 compliance status: copies, media_count, offsite, compliant."""
    policy = get_321_policy(vm_id)
    if not policy:
        return {"vm_id": vm_id, "policy_set": False, "compliant": False}
    last = policy.get("last_run") or {}
    return {
        "vm_id":       vm_id,
        "policy_set":  True,
        "copies":      last.get("copies", 0),
        "media_count": last.get("media_count", 0),
        "offsite":     last.get("offsite", {}),
        "compliant":   last.get("compliant", False),
        "last_run_ts": last.get("ts"),
        "run_id":      last.get("run_id"),
    }






