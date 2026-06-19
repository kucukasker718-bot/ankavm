"""
ankavm Content Library Manager
Centralized ISO + VM template repository.
Supports local storage and URL-based remote items.
Storage: /var/lib/ankavm/content_library.json
Files: /var/lib/libvirt/images/content-library/
"""
import json, uuid, os, shutil, subprocess, logging, threading, hashlib
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ankavm.content_library")
_LIBRARY_FILE  = Path("/var/lib/ankavm/content_library.json")
_LIBRARY_DIR   = Path("/var/lib/libvirt/images/content-library")
_lock = threading.Lock()


def _load():
    try:
        if _LIBRARY_FILE.exists():
            return json.loads(_LIBRARY_FILE.read_text())
    except Exception:
        pass
    return []


def _save(data):
    _LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LIBRARY_FILE.write_text(json.dumps(data, indent=2))


def list_items():
    items = []
    with _lock:
        stored = {i["id"]: i for i in _load()}

    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    for fpath in _LIBRARY_DIR.iterdir():
        if fpath.is_file():
            fid = hashlib.sha256(str(fpath).encode()).hexdigest()[:16]
            meta = stored.get(fid, {})
            stat = fpath.stat()
            items.append({
                "id":          meta.get("id", fid),
                "name":        meta.get("name", fpath.name),
                "description": meta.get("description", ""),
                "type":        meta.get("type", _guess_type(fpath.name)),
                "tags":        meta.get("tags", []),
                "size":        stat.st_size,
                "filename":    fpath.name,
                "path":        str(fpath),
                "created_at":  meta.get("created_at",
                               datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat()),
            })
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


def _guess_type(filename):
    fn = filename.lower()
    if fn.endswith(".iso"):
        return "iso"
    if fn.endswith((".qcow2", ".vmdk", ".vdi", ".raw", ".img")):
        return "disk_template"
    return "other"


def add_item(name, description="", item_type="iso", tags=None, source_path=None, url=None):
    """Register an existing file or download from URL."""
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    item_id = str(uuid.uuid4())[:16]

    if source_path and os.path.isfile(source_path):
        dest = _LIBRARY_DIR / Path(source_path).name
        if str(source_path) != str(dest):
            shutil.copy2(source_path, dest)
        filename = dest.name
    elif url:
        filename = url.split("/")[-1].split("?")[0] or f"item-{item_id}.bin"
        dest = _LIBRARY_DIR / filename
        try:
            r = subprocess.run(
                ["curl", "-fL", "-o", str(dest), "--progress-bar", url],
                capture_output=True, timeout=300
            )
            if r.returncode != 0:
                return {"ok": False, "error": "Download failed: " + r.stderr.decode()[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        return {"ok": False, "error": "source_path or url required"}

    item = {
        "id": item_id,
        "name": name or filename,
        "description": description,
        "type": item_type,
        "tags": tags or [],
        "filename": filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return {"ok": True, "item": item}


def delete_item(item_id):
    with _lock:
        items = _load()
        target = next((i for i in items if i["id"] == item_id), None)
        if not target:
            return False
        fpath = _LIBRARY_DIR / target["filename"]
        if fpath.exists():
            fpath.unlink()
        new_items = [i for i in items if i["id"] != item_id]
        _save(new_items)
    return True


def get_item(item_id):
    with _lock:
        for i in _load():
            if i["id"] == item_id:
                return i
    return None


def sync_from_iso_pool(iso_dir="/var/lib/libvirt/images"):
    """Import existing ISOs from the main ISO pool into content library."""
    _LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    imported = []
    for fpath in Path(iso_dir).iterdir():
        if fpath.is_file() and fpath.suffix.lower() == ".iso":
            dest = _LIBRARY_DIR / fpath.name
            if not dest.exists():
                os.link(fpath, dest)  # hard link, no extra space
                imported.append(fpath.name)
    return {"imported": imported, "count": len(imported)}


def get_stats():
    items = list_items()
    total_bytes = sum(i.get("size", 0) for i in items)
    by_type = {}
    for i in items:
        t = i.get("type", "other")
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "total": len(items),
        "total_bytes": total_bytes,
        "by_type": by_type,
    }






