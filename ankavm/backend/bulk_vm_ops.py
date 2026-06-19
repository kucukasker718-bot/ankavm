"""
ankavm Bulk VM Operations
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Apply tag/network/cpu/memory changes to multiple VMs simultaneously.
All operations are idempotent and logged.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_log = logging.getLogger("ankavm.bulk_vm_ops")

_JOBS_FILE = Path("/var/lib/ankavm/bulk_jobs.json")
_AUDIT_FILE = Path("/var/lib/ankavm/bulk_audit.jsonl")
_JOBS_LOCK = threading.Lock()
_MAX_WORKERS = 4

# SEC-025: confirm_token nonce store. Each call without a token mints a fresh
# nonce that is bound to the exact VM-id set and expires after 5 minutes.
_NONCE_TTL = 300
_NONCES: dict = {}  # nonce -> {vm_ids_hash, expires_at}
_NONCE_LOCK = threading.Lock()

_CONFIRM_KEY = os.environ.get(
    "ankavm_BULK_CONFIRM_KEY",
    "ankavm-bulk-confirm-rotates-on-restart",
).encode("utf-8")

# _safe_import vm_manager
try:
    import vm_manager as _vm_manager
except ImportError:
    try:
        from ankavm.backend import vm_manager as _vm_manager
    except ImportError:
        _vm_manager = None

# _safe_import tag_manager
try:
    import tag_manager as _tag_manager
except ImportError:
    try:
        from ankavm.backend import tag_manager as _tag_manager
    except ImportError:
        _tag_manager = None


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def _run_nofail(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _load_jobs() -> dict:
    try:
        if _JOBS_FILE.exists():
            return json.loads(_JOBS_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_jobs(data: dict):
    _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _JOBS_FILE.write_text(json.dumps(data, indent=2))


def _record_job(job_id: str, op: str, vm_ids: list, result: dict):
    with _JOBS_LOCK:
        jobs = _load_jobs()
        jobs[job_id] = {
            "id": job_id,
            "op": op,
            "vm_ids": vm_ids,
            "result": result,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # keep last 200 jobs
        if len(jobs) > 200:
            oldest = sorted(jobs, key=lambda k: jobs[k].get("timestamp", ""))[:len(jobs) - 200]
            for k in oldest:
                jobs.pop(k, None)
        _save_jobs(jobs)


def _parallel(fn, vm_ids: list, **kwargs) -> dict:
    success, failed = [], []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(fn, vm_id, **kwargs): vm_id for vm_id in vm_ids}
        for future in as_completed(futures):
            vm_id = futures[future]
            try:
                res = future.result()
                if isinstance(res, dict) and not res.get("success", True):
                    failed.append({"vm_id": vm_id, "error": res.get("message") or res.get("error") or "unknown"})
                else:
                    success.append({"vm_id": vm_id, "result": res})
            except Exception as e:
                failed.append({"vm_id": vm_id, "error": str(e)})
    return {"success": success, "failed": failed}


# â”€â”€â”€ power â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _start_one(vm_id: str) -> dict:
    r = _run_nofail(["virsh", "start", vm_id])
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def _stop_one(vm_id: str, force: bool = False) -> dict:
    cmd = ["virsh", "destroy" if force else "shutdown", vm_id]
    r = _run_nofail(cmd)
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def bulk_start(vm_ids: list) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_start_one, vm_ids)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_start", vm_ids, result)
    return result


def bulk_stop(vm_ids: list, force: bool = False) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_stop_one, vm_ids, force=force)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_stop", vm_ids, result)
    return result


# â”€â”€â”€ snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _snapshot_one(vm_id: str, snap_name: str) -> dict:
    r = _run_nofail(["virsh", "snapshot-create-as", vm_id, snap_name])
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def bulk_snapshot(vm_ids: list, snap_name: str) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_snapshot_one, vm_ids, snap_name=snap_name)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_snapshot", vm_ids, result)
    return result


# â”€â”€â”€ tags â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _add_tag_one(vm_id: str, tag: str) -> dict:
    if _tag_manager is not None:
        try:
            tags = _tag_manager.add_tag(vm_id, tag)
            return {"success": True, "tags": tags}
        except Exception as e:
            return {"success": False, "message": str(e)}
    # fallback: no-op
    return {"success": False, "message": "tag_manager unavailable"}


def _remove_tag_one(vm_id: str, tag: str) -> dict:
    if _tag_manager is not None:
        try:
            _tag_manager.remove_tag(vm_id, tag)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}
    return {"success": False, "message": "tag_manager unavailable"}


def bulk_add_tag(vm_ids: list, tag: str) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_add_tag_one, vm_ids, tag=tag)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_add_tag", vm_ids, result)
    return result


def bulk_remove_tag(vm_ids: list, tag: str) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_remove_tag_one, vm_ids, tag=tag)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_remove_tag", vm_ids, result)
    return result


# â”€â”€â”€ network â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _set_network_one(vm_id: str, network_name: str) -> dict:
    # Requires VM to be stopped. Attach new interface via virsh attach-interface --config.
    r_state = _run_nofail(["virsh", "domstate", vm_id])
    state = r_state.stdout.strip()
    if state not in ("shut off", "shutoff"):
        return {
            "success": False,
            "message": f"VM must be stopped (current state: {state})",
        }
    r = _run_nofail([
        "virsh", "attach-interface", vm_id,
        "network", network_name,
        "--model", "virtio",
        "--config",
    ])
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def bulk_set_network(vm_ids: list, network_name: str) -> dict:
    job_id = str(uuid.uuid4())
    result = _parallel(_set_network_one, vm_ids, network_name=network_name)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_set_network", vm_ids, result)
    return result


# â”€â”€â”€ vcpus â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _set_vcpus_one(vm_id: str, vcpus: int) -> dict:
    r_state = _run_nofail(["virsh", "domstate", vm_id])
    state = r_state.stdout.strip()
    running = state == "running"
    args = ["virsh", "setvcpus", vm_id, str(vcpus), "--config"]
    if running:
        args.append("--live")
    r = _run_nofail(args)
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def bulk_set_vcpus(vm_ids: list, vcpus: int) -> dict:
    if vcpus < 1:
        return {"success": [], "failed": [{"vm_id": v, "error": "vcpus must be >= 1"} for v in vm_ids], "job_id": ""}
    job_id = str(uuid.uuid4())
    result = _parallel(_set_vcpus_one, vm_ids, vcpus=vcpus)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_set_vcpus", vm_ids, result)
    return result


# â”€â”€â”€ memory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _set_memory_one(vm_id: str, memory_mb: int) -> dict:
    memory_kb = memory_mb * 1024
    r_state = _run_nofail(["virsh", "domstate", vm_id])
    state = r_state.stdout.strip()
    running = state == "running"
    args = ["virsh", "setmem", vm_id, str(memory_kb), "--config"]
    if running:
        args.append("--live")
    r = _run_nofail(args)
    ok = r.returncode == 0
    return {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}


def bulk_set_memory(vm_ids: list, memory_mb: int) -> dict:
    if memory_mb < 64:
        return {"success": [], "failed": [{"vm_id": v, "error": "memory_mb must be >= 64"} for v in vm_ids], "job_id": ""}
    job_id = str(uuid.uuid4())
    result = _parallel(_set_memory_one, vm_ids, memory_mb=memory_mb)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_set_memory", vm_ids, result)
    return result


# â”€â”€â”€ delete â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _vm_ids_hash(vm_ids: list) -> str:
    payload = ",".join(sorted(vm_ids)).encode("utf-8")
    return hmac.new(_CONFIRM_KEY, payload, hashlib.sha256).hexdigest()


def _mint_confirm_token(vm_ids: list) -> str:
    """SEC-025: confirm_token is a fresh random nonce bound server-side to a
    specific VM-id set + a 5-minute expiry. Pre-image is unguessable even with
    full knowledge of the VM list."""
    nonce = secrets.token_urlsafe(24)
    now = time.time()
    with _NONCE_LOCK:
        # prune expired
        for k in [k for k, v in _NONCES.items() if v["expires_at"] < now]:
            _NONCES.pop(k, None)
        _NONCES[nonce] = {
            "vm_ids_hash": _vm_ids_hash(vm_ids),
            "expires_at": now + _NONCE_TTL,
        }
    return nonce


def _consume_confirm_token(token: str, vm_ids: list) -> bool:
    if not token:
        return False
    now = time.time()
    expected_hash = _vm_ids_hash(vm_ids)
    with _NONCE_LOCK:
        entry = _NONCES.pop(token, None)
    if not entry:
        return False
    if entry["expires_at"] < now:
        return False
    return hmac.compare_digest(entry["vm_ids_hash"], expected_hash)


def _per_vm_audit(op: str, vm_id: str, result: dict, requester: str = "system"):
    """SEC-026: each VM-affecting op gets its own audit-log line so admins can
    trace exactly which VM was acted on, by whom, when, and with what outcome."""
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "op": op,
            "vm_id": vm_id,
            "ok": bool(result.get("success", False)),
            "message": result.get("message", "")[:500],
            "requester": requester,
        }
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        _log.warning("per-VM audit write failed: %s", e)


def _delete_one(vm_id: str, delete_disk: bool = False, requester: str = "system") -> dict:
    _run_nofail(["virsh", "destroy", vm_id])
    args = ["virsh", "undefine", vm_id]
    if delete_disk:
        args.append("--remove-all-storage")
    r = _run_nofail(args)
    ok = r.returncode == 0
    result = {"success": ok, "message": (r.stdout.strip() or r.stderr.strip())}
    _per_vm_audit("bulk_delete", vm_id, result, requester=requester)
    return result


def bulk_delete(vm_ids: list, delete_disk: bool = False, confirm_token: str = "",
                requester: str = "system") -> dict:
    if not _consume_confirm_token(confirm_token, vm_ids):
        nonce = _mint_confirm_token(vm_ids)
        return {
            "success": [],
            "failed": [],
            "job_id": "",
            "requires_confirmation": True,
            "confirm_token": nonce,
            "expires_in_sec": _NONCE_TTL,
            "message": (
                f"Pass confirm_token='{nonce}' within {_NONCE_TTL}s to confirm "
                f"deletion of {len(vm_ids)} VM(s). Token is single-use and bound "
                f"to this exact VM list."
            ),
        }
    job_id = str(uuid.uuid4())
    result = _parallel(_delete_one, vm_ids, delete_disk=delete_disk, requester=requester)
    result["job_id"] = job_id
    _record_job(job_id, "bulk_delete", vm_ids, result)
    return result


# â”€â”€â”€ job status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_bulk_status(job_id: str) -> dict:
    with _JOBS_LOCK:
        jobs = _load_jobs()
    job = jobs.get(job_id)
    if not job:
        return {"found": False, "job_id": job_id}
    return {"found": True, **job}






