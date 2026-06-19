"""
ankavm VNC Thumbnail Manager
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Ã‡alÄ±ÅŸan VM'lerden VNC Ã¼zerinden ekran gÃ¶rÃ¼ntÃ¼sÃ¼ alÄ±r (5 dk cache).
VM liste sayfasÄ±nda canlÄ± Ã¶nizleme iÃ§in.

API:
    get_thumbnail(vm_id) -> bytes | None
    refresh_all() -> int  (background)
    invalidate(vm_id)
"""

import os, time, threading, logging, hashlib, subprocess
from pathlib import Path

log = logging.getLogger("vnc_thumbnail")

_CACHE_DIR = Path("/var/lib/ankavm/thumbnails")
_CACHE_TTL = 300                      # 5 dakika
_LOCK      = threading.Lock()
_IN_FLIGHT = set()                    # paralel duplicate Ã¶nle


def _path_for(vm_id: str) -> Path:
    safe = hashlib.sha256(vm_id.encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{safe}.png"


def _capture_via_virsh(vm_name: str, out_path: Path) -> bool:
    """virsh screenshot ile PNG yakala. VM Ã§alÄ±ÅŸÄ±yorsa."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_ppm = out_path.with_suffix(".ppm")
        # virsh screenshot domain file --screen 0
        r = subprocess.run(
            ["virsh", "screenshot", vm_name, str(tmp_ppm), "--screen", "0"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0 or not tmp_ppm.exists():
            log.debug("virsh screenshot baÅŸarÄ±sÄ±z (%s): %s", vm_name, r.stderr.strip())
            return False
        # PPM â†’ PNG (kÃ¼Ã§Ã¼lt)
        png_out = subprocess.run(
            ["convert", str(tmp_ppm), "-resize", "320x180", "-quality", "70", str(out_path)],
            capture_output=True, timeout=10
        )
        try:
            tmp_ppm.unlink()
        except Exception:
            pass
        return out_path.exists()
    except FileNotFoundError as e:
        log.warning("Gerekli komut bulunamadÄ± (virsh veya convert): %s", e)
        return False
    except Exception as e:
        log.warning("Thumbnail capture hatasÄ± %s: %s", vm_name, e)
        return False


def get_thumbnail(vm_id: str, vm_name: str = None) -> bytes:
    """Cache'ten dÃ¶n, yoksa yakala. None = Ã§ekilemedi."""
    if not vm_id:
        return None
    p = _path_for(vm_id)
    if p.exists():
        age = time.time() - p.stat().st_mtime
        if age < _CACHE_TTL:
            try:
                return p.read_bytes()
            except Exception:
                pass

    # Anti-stampede: aynÄ± VM iÃ§in paralel istekleri engelle
    with _LOCK:
        if vm_id in _IN_FLIGHT:
            # Eski cache varsa onu dÃ¶n
            if p.exists():
                try:
                    return p.read_bytes()
                except Exception:
                    pass
            return None
        _IN_FLIGHT.add(vm_id)

    try:
        if not vm_name:
            vm_name = vm_id
        ok = _capture_via_virsh(vm_name, p)
        if ok:
            return p.read_bytes()
    finally:
        with _LOCK:
            _IN_FLIGHT.discard(vm_id)
    return None


def invalidate(vm_id: str):
    """Cache'i sil â€” VM aksiyonu sonrasÄ± tetiklenir (start/reboot)."""
    try:
        p = _path_for(vm_id)
        if p.exists():
            p.unlink()
    except Exception:
        pass


def refresh_all(vm_list: list) -> int:
    """TÃ¼m Ã§alÄ±ÅŸan VM'leri arka planda yenile. vm_list = [{id, name, state}]"""
    count = 0
    for v in vm_list:
        if v.get("state") != "running":
            continue
        try:
            get_thumbnail(v["id"], v.get("name"))
            count += 1
        except Exception:
            pass
    return count


def stats() -> dict:
    """Cache istatistikleri."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        files = list(_CACHE_DIR.glob("*.png"))
        total_bytes = sum(f.stat().st_size for f in files)
        return {
            "cached":      len(files),
            "total_bytes": total_bytes,
            "total_mb":    round(total_bytes / (1024 * 1024), 2),
            "ttl_seconds": _CACHE_TTL,
            "cache_dir":   str(_CACHE_DIR),
        }
    except Exception as e:
        return {"error": str(e)}






