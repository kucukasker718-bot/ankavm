"""
ankavm Lifecycle Manager â€” Rolling host upgrade & config drift
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
- Host paketlerini gÃ¼ncelle (rolling, VM downtime'sÄ±z single-host iÃ§in en azÄ±ndan ÅŸedÃ¼ller)
- Config drift detection (hash compare)
- Update notification

API:
    check_updates() -> dict
    apply_updates(packages, dry_run=False) -> dict
    capture_baseline(name='production') -> dict
    detect_drift(baseline_name='production') -> dict
"""

import os, json, subprocess, time, hashlib, logging
from pathlib import Path

log = logging.getLogger("lifecycle_manager")

_BASELINES = Path("/var/lib/ankavm/config_baselines.json")

_TRACKED_FILES = [
    "/etc/sysctl.conf",
    "/etc/network/interfaces",
    "/etc/ssh/sshd_config",
    "/etc/libvirt/libvirtd.conf",
    "/etc/libvirt/qemu.conf",
    "/etc/iptables/rules.v4",
    "/etc/nginx/nginx.conf",
    "/etc/ankavm/config.json",
]


def check_updates() -> dict:
    """apt list --upgradable parse."""
    try:
        # Sessiz update DB
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=60)
        r = subprocess.run(["apt", "list", "--upgradable"],
                           capture_output=True, text=True, timeout=30)
        lines = [l for l in r.stdout.splitlines() if "/" in l and "upgradable" in l]
        pkgs = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0].split("/")[0]
                version = parts[1]
                pkgs.append({"name": name, "version": version})
        # Security update count
        sec_count = sum(1 for l in lines if "-security" in l or "Ubuntu-Security" in l)
        return {
            "available":         len(pkgs),
            "security_updates":  sec_count,
            "packages":          pkgs[:200],   # sÄ±nÄ±rla
            "reboot_required":   Path("/var/run/reboot-required").exists(),
            "checked_at":        int(time.time()),
        }
    except Exception as e:
        return {"error": str(e)}


def apply_updates(packages: list = None, dry_run: bool = False,
                   security_only: bool = False) -> dict:
    """Paket gÃ¼ncelle. dry_run â†’ --dry-run. packages None â†’ tÃ¼m gÃ¼ncellemeler."""
    cmd = ["apt-get"]
    if security_only:
        # unattended-upgrades varsa onu kullan
        cmd = ["unattended-upgrade", "--dry-run" if dry_run else ""]
    else:
        cmd += ["install", "-y", "--only-upgrade"]
        if dry_run:
            cmd.append("--dry-run")
        if packages:
            cmd += packages
        else:
            cmd[1] = "upgrade"
            if "install" in cmd: cmd.remove("install")
            if "--only-upgrade" in cmd: cmd.remove("--only-upgrade")
    cmd = [c for c in cmd if c]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        return {
            "ok":         r.returncode == 0,
            "dry_run":    dry_run,
            "stdout":     r.stdout[-4000:],
            "stderr":     r.stderr[-1000:],
            "returncode": r.returncode,
            "reboot_required": Path("/var/run/reboot-required").exists(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Update timeout (10 dk)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _hash_file(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def capture_baseline(name: str = "production") -> dict:
    """Mevcut config dosyalarÄ±nÄ±n hash'ini snapshot al."""
    snapshot = {
        "name":       name,
        "captured":   int(time.time()),
        "files":      {},
    }
    for f in _TRACKED_FILES:
        if Path(f).exists():
            snapshot["files"][f] = {
                "hash":  _hash_file(f),
                "size":  Path(f).stat().st_size,
                "mtime": int(Path(f).stat().st_mtime),
            }

    _BASELINES.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if _BASELINES.exists():
        try:
            existing = json.loads(_BASELINES.read_text())
        except Exception:
            pass
    existing[name] = snapshot
    _BASELINES.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    return snapshot


def list_baselines() -> list:
    if not _BASELINES.exists():
        return []
    try:
        data = json.loads(_BASELINES.read_text())
        return [{"name": k, **v} for k, v in data.items()]
    except Exception:
        return []


def detect_drift(baseline_name: str = "production") -> dict:
    """Baseline'a gÃ¶re deÄŸiÅŸen dosyalarÄ± bul."""
    if not _BASELINES.exists():
        return {"error": "Baseline yok â€” Ã¶nce capture_baseline Ã§alÄ±ÅŸtÄ±r"}
    baselines = json.loads(_BASELINES.read_text())
    base = baselines.get(baseline_name)
    if not base:
        return {"error": f"Baseline bulunamadÄ±: {baseline_name}"}

    drifted = []
    new_files = []
    deleted = []
    for f, info in base["files"].items():
        if not Path(f).exists():
            deleted.append(f)
            continue
        current_hash = _hash_file(f)
        if current_hash != info["hash"]:
            drifted.append({
                "file":         f,
                "old_hash":     info["hash"],
                "new_hash":     current_hash,
                "old_size":     info["size"],
                "new_size":     Path(f).stat().st_size,
                "changed_ago":  int(time.time() - Path(f).stat().st_mtime),
            })

    # Track edilen ama baseline'da olmayan
    for f in _TRACKED_FILES:
        if f not in base["files"] and Path(f).exists():
            new_files.append(f)

    return {
        "baseline":     baseline_name,
        "drift_count":  len(drifted) + len(deleted) + len(new_files),
        "drifted":      drifted,
        "deleted":      deleted,
        "new_files":    new_files,
        "captured_at":  base["captured"],
        "compared_at":  int(time.time()),
    }


def rolling_upgrade(target_packages: list = None, vms_per_batch: int = 5,
                     delay_sec: int = 30) -> dict:
    """
    Rolling upgrade â€” VM'leri batch'lerle taÅŸÄ±/durdur, paket gÃ¼ncelle, geri baÅŸlat.
    Bu basit single-host: sadece warning + gÃ¼ncellemeyi tetikle.
    Multi-host implementation cluster_manager gerektirir.
    """
    return {
        "ok":      False,
        "message": "Rolling upgrade multi-node cluster gerektirir. "
                   "Tek node iÃ§in: maintenance_mode â†’ apply_updates â†’ reboot â†’ exit_maintenance",
        "steps_suggestion": [
            "1. maintenance_mode.enter_maintenance(graceful)",
            "2. lifecycle_manager.apply_updates(security_only=True)",
            "3. Reboot if needed",
            "4. maintenance_mode.exit_maintenance(auto_start=True)",
        ],
    }






