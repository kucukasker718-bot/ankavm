"""
ankavm vSAN Manager — Ceph-backed distributed storage.
Provides vSAN-style abstraction over an existing Ceph cluster.
Storage: /var/lib/ankavm/vsan_config.json
"""
import json, subprocess, logging, threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ankavm.vsan")
_CONFIG_FILE = Path("/var/lib/ankavm/vsan_config.json")
_lock = threading.Lock()

DEFAULT_CONFIG = {
    "enabled": False,
    "mode": "ceph",          # ceph | nfs_cluster
    "ceph_mon": "",          # monitor IP/hostname
    "ceph_user": "admin",
    "ceph_pool": "ankavm",
    "nfs_server": "",
    "nfs_path": "/exports/vsan",
    "replication": 2,
    "created_at": None,
}


def _load():
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text())
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def _save(cfg):
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_config():
    with _lock:
        return _load()


def save_config(enabled, mode="ceph", ceph_mon="", ceph_user="admin",
                ceph_pool="ankavm", nfs_server="", nfs_path="/exports/vsan",
                replication=2):
    with _lock:
        cfg = _load()
        cfg.update({
            "enabled": bool(enabled),
            "mode": mode,
            "ceph_mon": str(ceph_mon).strip(),
            "ceph_user": str(ceph_user).strip(),
            "ceph_pool": str(ceph_pool).strip(),
            "nfs_server": str(nfs_server).strip(),
            "nfs_path": str(nfs_path).strip(),
            "replication": int(replication),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if not cfg.get("created_at"):
            cfg["created_at"] = cfg["updated_at"]
        _save(cfg)
        return cfg


def get_status():
    """Return vSAN cluster health: ceph status or NFS mount info."""
    cfg = _load()
    if not cfg.get("enabled"):
        return {"enabled": False, "status": "disabled", "health": None}

    if cfg["mode"] == "ceph":
        try:
            r = subprocess.run(
                ["ceph", "-s", "--format", "json"],
                capture_output=True, text=True, timeout=8
            )
            if r.returncode == 0:
                import json as _j
                data = _j.loads(r.stdout)
                health = data.get("health", {}).get("status", "unknown")
                osd = data.get("osdmap", {})
                pg = data.get("pgmap", {})
                return {
                    "enabled": True, "status": "online",
                    "health": health,
                    "osds_total": osd.get("num_osds", 0),
                    "osds_up": osd.get("num_up_osds", 0),
                    "osds_in": osd.get("num_in_osds", 0),
                    "pgs": pg.get("num_pgs", 0),
                    "bytes_total": pg.get("bytes_total", 0),
                    "bytes_used": pg.get("bytes_used", 0),
                    "bytes_avail": pg.get("bytes_avail", 0),
                    "write_bytes_sec": pg.get("write_bytes_sec", 0),
                    "read_bytes_sec": pg.get("read_bytes_sec", 0),
                }
            return {"enabled": True, "status": "error", "error": r.stderr.strip()[:200]}
        except FileNotFoundError:
            return {"enabled": True, "status": "ceph_not_installed",
                    "error": "ceph CLI not found — install ceph-common"}
        except Exception as e:
            return {"enabled": True, "status": "error", "error": str(e)}

    elif cfg["mode"] == "nfs_cluster":
        try:
            r = subprocess.run(["df", "-h", cfg["nfs_path"]], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                return {
                    "enabled": True, "status": "online", "health": "OK",
                    "path": cfg["nfs_path"],
                    "size": parts[1] if len(parts) > 1 else "?",
                    "used": parts[2] if len(parts) > 2 else "?",
                    "avail": parts[3] if len(parts) > 3 else "?",
                    "use_pct": parts[4] if len(parts) > 4 else "?",
                }
        except Exception as e:
            return {"enabled": True, "status": "error", "error": str(e)}

    return {"enabled": True, "status": "unknown_mode"}


def get_osds():
    """List Ceph OSD tree."""
    try:
        r = subprocess.run(
            ["ceph", "osd", "tree", "--format", "json"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            import json as _j
            return _j.loads(r.stdout).get("nodes", [])
    except Exception:
        pass
    return []


def get_pools():
    """List Ceph pools with usage stats."""
    try:
        r = subprocess.run(
            ["ceph", "df", "--format", "json"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            import json as _j
            data = _j.loads(r.stdout)
            return data.get("pools", [])
    except Exception:
        pass
    return []


def create_pool(name, pg_num=32, replication=2):
    """Create a Ceph pool for vSAN."""
    try:
        r = subprocess.run(
            ["ceph", "osd", "pool", "create", name, str(pg_num)],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            subprocess.run(
                ["ceph", "osd", "pool", "set", name, "size", str(replication)],
                capture_output=True, timeout=5
            )
            return {"ok": True, "pool": name}
        return {"ok": False, "error": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}






