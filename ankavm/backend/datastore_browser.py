"""
ankavm Datastore Browser
Browse, upload, download, and delete files in storage pool directories.
"""
import os, subprocess, hashlib, mimetypes, logging
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger("ankavm.datastore")

ALLOWED_EXTENSIONS = {
    ".iso", ".qcow2", ".vmdk", ".vdi", ".raw", ".img",
    ".ovf", ".ova", ".xml", ".json", ".sh", ".conf",
    ".log", ".txt", ".tar", ".gz", ".xz", ".bz2", ".zip",
}

ALLOWED_ROOT_PATHS = [
    "/var/lib/libvirt/images",
    "/var/lib/ankavm",
    "/tmp/ankavm-uploads",
]


def _safe_path(pool_path, rel_path=""):
    """Resolve path safely under an allowed root."""
    base = Path(pool_path).resolve()
    # Check base is under an allowed root
    allowed = any(str(base).startswith(root) for root in ALLOWED_ROOT_PATHS)
    if not allowed:
        raise PermissionError(f"Path {base} not in allowed roots")

    if rel_path:
        target = (base / rel_path).resolve()
        if not str(target).startswith(str(base)):
            raise PermissionError("Path traversal detected")
        return target
    return base


def list_directory(pool_path, rel_path=""):
    """List files and directories at path."""
    try:
        base = _safe_path(pool_path, rel_path)
        if not base.exists():
            return {"ok": False, "error": f"Path not found: {base}"}

        items = []
        for entry in sorted(base.iterdir()):
            try:
                stat = entry.stat()
                items.append({
                    "name":       entry.name,
                    "type":       "dir" if entry.is_dir() else "file",
                    "size":       stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "modified":   datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "ext":        entry.suffix.lower(),
                    "rel_path":   str(Path(rel_path) / entry.name) if rel_path else entry.name,
                })
            except Exception:
                continue

        return {
            "ok": True,
            "path": str(base),
            "rel_path": rel_path,
            "pool_path": pool_path,
            "items": items,
            "count": len(items),
        }
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log.error("list_directory: %s", e)
        return {"ok": False, "error": str(e)}


def _human_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def get_file_info(pool_path, rel_path):
    """Get detailed info about a single file."""
    try:
        full = _safe_path(pool_path, rel_path)
        if not full.exists():
            return {"ok": False, "error": "File not found"}
        stat = full.stat()
        info = {
            "ok": True,
            "name": full.name,
            "path": str(full),
            "size": stat.st_size,
            "size_human": _human_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "ext": full.suffix.lower(),
            "mime": mimetypes.guess_type(full.name)[0] or "application/octet-stream",
        }
        # qemu-img info for disk images
        if full.suffix.lower() in {".qcow2", ".vmdk", ".vdi", ".raw", ".img"}:
            try:
                r = subprocess.run(
                    ["qemu-img", "info", "--output=json", str(full)],
                    capture_output=True, text=True, timeout=10
                )
                if r.returncode == 0:
                    import json as _j
                    info["qemu_info"] = _j.loads(r.stdout)
            except Exception:
                pass
        return info
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_file(pool_path, rel_path):
    """Delete a file from a datastore."""
    try:
        full = _safe_path(pool_path, rel_path)
        if not full.exists():
            return {"ok": False, "error": "File not found"}
        if full.is_dir():
            return {"ok": False, "error": "Use rmdir for directories"}
        full.unlink()
        return {"ok": True, "deleted": str(full)}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def rename_file(pool_path, rel_path, new_name):
    """Rename a file within the same directory."""
    try:
        full = _safe_path(pool_path, rel_path)
        if not full.exists():
            return {"ok": False, "error": "File not found"}
        new_name = Path(new_name).name  # strip any directory components
        dest = full.parent / new_name
        full.rename(dest)
        return {"ok": True, "new_path": str(dest)}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def create_directory(pool_path, rel_path, dir_name):
    try:
        base = _safe_path(pool_path, rel_path)
        new_dir = (base / Path(dir_name).name).resolve()
        if not str(new_dir).startswith(str(_safe_path(pool_path))):
            return {"ok": False, "error": "Invalid directory name"}
        new_dir.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(new_dir)}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_disk_usage(pool_path):
    """Get df-style usage for a pool path."""
    try:
        r = subprocess.run(["df", "-h", pool_path], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            return {
                "ok": True,
                "device": parts[0] if parts else "",
                "size": parts[1] if len(parts) > 1 else "",
                "used": parts[2] if len(parts) > 2 else "",
                "avail": parts[3] if len(parts) > 3 else "",
                "use_pct": parts[4] if len(parts) > 4 else "",
                "mount": parts[5] if len(parts) > 5 else pool_path,
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "df failed"}






