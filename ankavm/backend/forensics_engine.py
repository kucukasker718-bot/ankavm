"""
ankavm Forensics â€” Memory dump + Packet capture per VM
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
- virsh dump <vm> <file>  â†’ full RAM dump (paused or live)
- tcpdump on VM's tap interface â†’ pcap file
- All artifacts stored under /var/lib/ankavm/forensics/<vm_id>/<ts>/

Captures are sized + checksummed. Pruning at /api/forensics/prune.
"""
from __future__ import annotations
import os, json, logging, subprocess, time, hashlib, signal
from pathlib import Path

log = logging.getLogger("forensics_engine")
_BASE = Path("/var/lib/ankavm/forensics")
_PCAP_JOBS = {}  # job_id -> {vm_id, pid, file, started}


def _vm_dir(vm_id: str) -> Path:
    d = _BASE / vm_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_dump(vm_id: str, mode: str = "live") -> dict:
    """virsh dump VM RAM to file."""
    ts   = time.strftime("%Y%m%d-%H%M%S")
    out  = _vm_dir(vm_id) / f"memdump-{ts}.bin"
    args = ["virsh", "dump", vm_id, str(out)]
    if mode == "live":
        args.append("--live")
    elif mode == "memory-only":
        args.append("--memory-only")
    else:
        args.append("--crash")  # paused dump
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()}
        size = out.stat().st_size
        sha  = _sha256_file(out)
        return {"ok": True, "path": str(out), "size_bytes": size, "sha256": sha,
                "mode": mode, "ts": ts}
    except FileNotFoundError:
        return {"ok": False, "error": "virsh not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _sha256_file(p: Path, block: int = 65536) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(block)
            if not b: break
            h.update(b)
    return h.hexdigest()


def _vm_tap_interface(vm_id: str) -> str:
    """Discover tap interface attached to VM (first interface)."""
    try:
        r = subprocess.run(["virsh", "domiflist", vm_id], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines()[2:]:  # skip headers
            parts = line.split()
            if parts:
                return parts[0]  # interface name
    except Exception:
        pass
    return ""


def packet_capture_start(vm_id: str, duration: int = 60, snaplen: int = 1500,
                         bpf_filter: str = "") -> dict:
    """Start tcpdump on VM tap. Limited duration to avoid disk fill."""
    iface = _vm_tap_interface(vm_id)
    if not iface:
        return {"ok": False, "error": "VM tap interface not found"}
    duration = max(5, min(600, int(duration)))  # clamp 5s-10min
    ts   = time.strftime("%Y%m%d-%H%M%S")
    out  = _vm_dir(vm_id) / f"pcap-{ts}.pcap"
    args = ["tcpdump", "-i", iface, "-s", str(snaplen), "-w", str(out), "-G", str(duration), "-W", "1"]
    if bpf_filter:
        args.extend(bpf_filter.split())
    try:
        # Spawn detached subprocess; track job
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        job_id = f"{vm_id}-{ts}"
        _PCAP_JOBS[job_id] = {
            "vm_id":   vm_id,
            "pid":     p.pid,
            "file":    str(out),
            "iface":   iface,
            "started": int(time.time()),
            "duration": duration,
        }
        return {"ok": True, "job_id": job_id, "file": str(out), "duration": duration}
    except FileNotFoundError:
        return {"ok": False, "error": "tcpdump not installed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def packet_capture_stop(job_id: str) -> dict:
    job = _PCAP_JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    try:
        os.kill(job["pid"], signal.SIGTERM)
    except Exception:
        pass
    try:
        p = Path(job["file"])
        size = p.stat().st_size if p.exists() else 0
    except Exception:
        size = 0
    job["stopped"] = int(time.time())
    job["size_bytes"] = size
    return {"ok": True, **job}


def list_jobs() -> list:
    return [{"id": k, **v} for k, v in _PCAP_JOBS.items()]


def list_artifacts(vm_id: str = None) -> list:
    """List all forensics artifacts under /var/lib/ankavm/forensics/"""
    out = []
    base = _BASE / vm_id if vm_id else _BASE
    if not base.exists():
        return out
    try:
        if vm_id:
            for f in base.iterdir():
                if f.is_file():
                    st = f.stat()
                    out.append({"vm_id": vm_id, "name": f.name, "size_bytes": st.st_size,
                                "mtime": int(st.st_mtime), "path": str(f)})
        else:
            for vd in base.iterdir():
                if vd.is_dir():
                    for f in vd.iterdir():
                        if f.is_file():
                            st = f.stat()
                            out.append({"vm_id": vd.name, "name": f.name, "size_bytes": st.st_size,
                                        "mtime": int(st.st_mtime), "path": str(f)})
    except Exception as e:
        log.warning("list_artifacts: %s", e)
    return sorted(out, key=lambda x: x["mtime"], reverse=True)


def delete_artifact(vm_id: str, name: str) -> dict:
    p = _BASE / vm_id / name
    try:
        if p.exists() and p.is_file():
            p.unlink()
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "not found"}


def prune(older_than_days: int = 30) -> dict:
    """Delete artifacts older than N days."""
    cutoff = time.time() - (older_than_days * 86400)
    deleted = 0
    try:
        for vd in _BASE.iterdir() if _BASE.exists() else []:
            for f in vd.iterdir() if vd.is_dir() else []:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
    except Exception:
        pass
    return {"ok": True, "deleted": deleted}






