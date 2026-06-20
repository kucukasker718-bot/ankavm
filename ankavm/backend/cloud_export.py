"""
ankavm Cloud Export — Workload Mobility (AWS / Azure / GCP)
────────────────────────────────────────────────────────────
Prepares VM disk images for cloud import:
  - AWS  → VMDK + import manifest (AMI prep)
  - Azure → VHD + manifest
  - GCP  → raw disk, tar.gz + manifest

Actual upload to cloud APIs is a stub (requires cloud SDK credentials
outside ankavm's scope). This module handles qemu-img conversion and
manifest generation using only stdlib + qemu-img subprocess.
No external Python deps. No periodic background jobs.
"""

import json
import time
import uuid
import logging
import threading
import subprocess
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("cloud_export")

_EXPORTS_FILE = Path("/var/lib/ankavm/cloud_exports.json")
_EXPORT_DIR   = Path("/var/lib/ankavm/cloud_export_staging")
_lock         = threading.Lock()

_SUPPORTED_TARGETS = {
    "aws": {
        "name":        "Amazon Web Services",
        "format":      "vmdk",
        "description": "VM Disk → VMDK → S3 → AMI import",
        "required_credentials": [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION",
            "S3_BUCKET",
        ],
        "docs": "https://docs.aws.amazon.com/vm-import/latest/userguide/vmimport-image-import.html",
    },
    "azure": {
        "name":        "Microsoft Azure",
        "format":      "vhd",
        "description": "VM Disk → VHD → Azure Blob → Managed Image",
        "required_credentials": [
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_RESOURCE_GROUP",
            "AZURE_STORAGE_ACCOUNT",
            "AZURE_STORAGE_KEY",
        ],
        "docs": "https://learn.microsoft.com/en-us/azure/virtual-machines/linux/upload-vhd",
    },
    "gcp": {
        "name":        "Google Cloud Platform",
        "format":      "raw.tar.gz",
        "description": "VM Disk → raw → disk.raw.tar.gz → GCS → Custom Image",
        "required_credentials": [
            "GCP_PROJECT_ID",
            "GCS_BUCKET",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ],
        "docs": "https://cloud.google.com/compute/docs/import/import-existing-image",
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_exports() -> list:
    try:
        if _EXPORTS_FILE.exists():
            return json.loads(_EXPORTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("cloud_export load fail: %s", e)
    return []


def _save_exports(data: list) -> None:
    try:
        _EXPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _EXPORTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_EXPORTS_FILE)
    except Exception as e:
        log.warning("cloud_export save fail: %s", e)


def _get_vm_disk(vm_id: str) -> Optional[str]:
    """Try to locate VM disk path via virsh."""
    try:
        r = subprocess.run(
            ["virsh", "domblklist", vm_id, "--details"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            parts = line.split()
            # virsh domblklist --details: type dev source
            if len(parts) >= 4 and parts[0] in ("file", "block"):
                path = parts[3]
                if path and path != "-" and Path(path).exists():
                    return path
    except Exception as ex:
        log.warning("get_vm_disk fail for %s: %s", vm_id, ex)
    return None


def _create_export_record(vm_id: str, target: str, extra: dict = None) -> dict:
    export_id = uuid.uuid4().hex[:12]
    record = {
        "id":          export_id,
        "vm_id":       vm_id,
        "target":      target,
        "status":      "pending",
        "created_at":  int(time.time()),
        "updated_at":  int(time.time()),
        "steps":       [],
        "output_path": None,
        "manifest":    None,
        **(extra or {}),
    }
    with _lock:
        exports = _load_exports()
        exports.append(record)
        _save_exports(exports)
    return record


def _update_export(export_id: str, **updates) -> None:
    with _lock:
        exports = _load_exports()
        for ex in exports:
            if ex["id"] == export_id:
                ex.update(updates)
                ex["updated_at"] = int(time.time())
                break
        _save_exports(exports)


def _add_step(export_id: str, step: str, ok: bool, detail: str = "") -> None:
    _update_export(export_id, **{})  # touch updated_at
    with _lock:
        exports = _load_exports()
        for ex in exports:
            if ex["id"] == export_id:
                ex.setdefault("steps", []).append({
                    "ts": int(time.time()), "step": step,
                    "ok": ok, "detail": detail
                })
                ex["updated_at"] = int(time.time())
                break
        _save_exports(exports)


def _qemu_convert(src: str, dst: str, fmt: str, export_id: str) -> bool:
    """Run qemu-img convert. Returns True on success."""
    if not shutil.which("qemu-img"):
        _add_step(export_id, "qemu-img check", False, "qemu-img not found on PATH")
        log.warning("qemu-img not available for export %s", export_id)
        return False
    try:
        r = subprocess.run(
            ["qemu-img", "convert", "-O", fmt, src, dst],
            capture_output=True, text=True, timeout=3600
        )
        ok = r.returncode == 0
        detail = r.stderr.strip()[:500] if not ok else ""
        _add_step(export_id, f"qemu-img convert to {fmt}", ok, detail)
        return ok
    except Exception as ex:
        _add_step(export_id, f"qemu-img convert to {fmt}", False, str(ex))
        return False


# ── public API ────────────────────────────────────────────────────────────────

def export_to_aws(vm_id: str, region: str = "us-east-1") -> dict:
    """
    Export VM disk to VMDK format with AWS import manifest.
    Actual S3 upload / AMI creation is a stub (requires AWS credentials).
    """
    record = _create_export_record(vm_id, "aws", {"region": region})
    export_id = record["id"]
    log.info("aws export started: vm=%s export=%s region=%s", vm_id, export_id, region)

    disk_path = _get_vm_disk(vm_id)
    if not disk_path:
        _add_step(export_id, "locate disk", False, "disk not found or VM offline")
        _update_export(export_id, status="failed")
        return {**record, "status": "failed",
                "error": "could not locate VM disk (is VM shut down?)"}

    _add_step(export_id, "locate disk", True, disk_path)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_vmdk = str(_EXPORT_DIR / f"{export_id}.vmdk")

    conv_ok = _qemu_convert(disk_path, out_vmdk, "vmdk", export_id)
    if not conv_ok:
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": "qemu-img conversion failed"}

    manifest = {
        "fileFormat":     "VMDK",
        "selfDestructUrl": None,
        "import": {
            "parts": [{"byteSize": None, "key": f"{export_id}.vmdk"}]
        },
        "region":    region,
        "exportedAt": int(time.time()),
        "vm_id":     vm_id,
        "engine":    "ankavm/cloud_export",
        "next_steps": [
            "1. Upload VMDK to S3: aws s3 cp <vmdk> s3://<BUCKET>/<KEY>",
            "2. Create import task: aws ec2 import-image --disk-containers <manifest>",
            "3. Monitor: aws ec2 describe-import-image-tasks --import-task-ids <task-id>",
        ],
    }
    manifest_path = str(_EXPORT_DIR / f"{export_id}_aws_manifest.json")
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _add_step(export_id, "write manifest", True, manifest_path)
    _add_step(export_id, "stub: s3 upload", False,
              "Upload stub — provide AWS credentials and run next_steps")

    _update_export(export_id, status="ready_for_upload",
                   output_path=out_vmdk, manifest=manifest)
    return {**record, "status": "ready_for_upload",
            "output_path": out_vmdk,
            "manifest_path": manifest_path,
            "manifest": manifest}


def export_to_azure(vm_id: str) -> dict:
    """
    Export VM disk to VHD with Azure import manifest.
    Actual Azure Blob upload is a stub.
    """
    record    = _create_export_record(vm_id, "azure")
    export_id = record["id"]
    log.info("azure export started: vm=%s export=%s", vm_id, export_id)

    disk_path = _get_vm_disk(vm_id)
    if not disk_path:
        _add_step(export_id, "locate disk", False, "disk not found")
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": "could not locate VM disk"}

    _add_step(export_id, "locate disk", True, disk_path)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_vhd = str(_EXPORT_DIR / f"{export_id}.vhd")

    conv_ok = _qemu_convert(disk_path, out_vhd, "vpc", export_id)
    if not conv_ok:
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": "qemu-img conversion failed"}

    manifest = {
        "format":     "VHD",
        "vm_id":      vm_id,
        "exportedAt": int(time.time()),
        "engine":     "ankavm/cloud_export",
        "next_steps": [
            "1. Upload VHD to Azure Blob Storage",
            "2. Create managed disk: az disk create --source <blob-uri>",
            "3. Create VM from disk: az vm create --attach-os-disk <disk>",
        ],
    }
    manifest_path = str(_EXPORT_DIR / f"{export_id}_azure_manifest.json")
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _add_step(export_id, "write manifest", True, manifest_path)
    _add_step(export_id, "stub: blob upload", False,
              "Upload stub — provide Azure credentials and run next_steps")

    _update_export(export_id, status="ready_for_upload",
                   output_path=out_vhd, manifest=manifest)
    return {**record, "status": "ready_for_upload",
            "output_path": out_vhd,
            "manifest_path": manifest_path,
            "manifest": manifest}


def export_to_gcp(vm_id: str) -> dict:
    """
    Export VM disk to raw tar.gz with GCP import manifest.
    Actual GCS upload is a stub.
    """
    record    = _create_export_record(vm_id, "gcp")
    export_id = record["id"]
    log.info("gcp export started: vm=%s export=%s", vm_id, export_id)

    disk_path = _get_vm_disk(vm_id)
    if not disk_path:
        _add_step(export_id, "locate disk", False, "disk not found")
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": "could not locate VM disk"}

    _add_step(export_id, "locate disk", True, disk_path)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_raw = str(_EXPORT_DIR / f"{export_id}_disk.raw")
    out_tar = str(_EXPORT_DIR / f"{export_id}_disk.raw.tar.gz")

    conv_ok = _qemu_convert(disk_path, out_raw, "raw", export_id)
    if not conv_ok:
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": "qemu-img conversion failed"}

    # Create tar.gz (GCP requires disk.raw inside a tar.gz)
    try:
        import tarfile
        with tarfile.open(out_tar, "w:gz") as tar:
            tar.add(out_raw, arcname="disk.raw")
        _add_step(export_id, "create tar.gz", True, out_tar)
        # Remove raw after tar
        try:
            Path(out_raw).unlink()
        except Exception:
            pass
    except Exception as ex:
        _add_step(export_id, "create tar.gz", False, str(ex))
        _update_export(export_id, status="failed")
        return {**record, "status": "failed", "error": f"tar creation failed: {ex}"}

    manifest = {
        "format":     "raw.tar.gz",
        "archive":    f"{export_id}_disk.raw",
        "vm_id":      vm_id,
        "exportedAt": int(time.time()),
        "engine":     "ankavm/cloud_export",
        "next_steps": [
            "1. Upload to GCS: gsutil cp <tar.gz> gs://<BUCKET>/",
            "2. Import image: gcloud compute images import <name> --source-file gs://<BUCKET>/<file>",
        ],
    }
    manifest_path = str(_EXPORT_DIR / f"{export_id}_gcp_manifest.json")
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _add_step(export_id, "write manifest", True, manifest_path)
    _add_step(export_id, "stub: gcs upload", False,
              "Upload stub — provide GCP credentials and run next_steps")

    _update_export(export_id, status="ready_for_upload",
                   output_path=out_tar, manifest=manifest)
    return {**record, "status": "ready_for_upload",
            "output_path": out_tar,
            "manifest_path": manifest_path,
            "manifest": manifest}


def list_exports() -> list:
    with _lock:
        return sorted(
            _load_exports(),
            key=lambda x: x.get("created_at", 0),
            reverse=True
        )


def get_export_status(export_id: str) -> Optional[dict]:
    with _lock:
        for ex in _load_exports():
            if ex["id"] == export_id:
                return ex
    return None


def get_supported_targets() -> dict:
    return _SUPPORTED_TARGETS






