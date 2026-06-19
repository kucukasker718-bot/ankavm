"""
ankavm Console Recorder
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Record VM VNC sessions as video using ffmpeg.
Recordings stored at /var/lib/ankavm/recordings/<vm_id>/
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

log = logging.getLogger("ankavm.console_recorder")

RECORDINGS_ROOT = "/var/lib/ankavm/recordings"
INDEX_PATH      = "/var/lib/ankavm/recordings/index.json"

_index_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------

def _load_index() -> dict:
    try:
        if os.path.exists(INDEX_PATH):
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error("_load_index: %s", e)
    return {}


def _save_index(data: dict):
    try:
        os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
        tmp = INDEX_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, INDEX_PATH)
    except Exception as e:
        log.error("_save_index: %s", e)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_recording(vm_id: str, vnc_port: int, duration_seconds: int = 3600) -> dict:
    """
    Start ffmpeg recording of a VNC session to WebM.
    Returns {recording_id, file_path, started_at, pid}.
    """
    if not _ffmpeg_available():
        return {"available": False, "error": "ffmpeg not installed"}

    recording_id = str(uuid.uuid4())
    out_dir      = os.path.join(RECORDINGS_ROOT, vm_id)
    os.makedirs(out_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_path = os.path.join(out_dir, f"{timestamp}_{recording_id[:8]}.webm")

    cmd = [
        "ffmpeg",
        "-f", "vnc",
        "-i", f"localhost:{vnc_port}",
        "-c:v", "libvpx",
        "-b:v", "1M",
        "-t", str(duration_seconds),
        "-y",
        file_path,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.error("start_recording(%s): %s", vm_id, e)
        return {"available": True, "error": str(e)}

    started_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "recording_id": recording_id,
        "vm_id":        vm_id,
        "file_path":    file_path,
        "started_at":   started_at,
        "stopped_at":   None,
        "pid":          proc.pid,
        "status":       "recording",
        "duration_seconds": None,
        "file_size_bytes":  None,
    }

    with _index_lock:
        index = _load_index()
        index[recording_id] = entry
        _save_index(index)

    log.info("start_recording: vm=%s recording_id=%s pid=%d", vm_id, recording_id, proc.pid)
    return {
        "recording_id": recording_id,
        "file_path":    file_path,
        "started_at":   started_at,
        "pid":          proc.pid,
    }


def stop_recording(recording_id: str) -> dict:
    """
    Stop an active ffmpeg recording.
    Returns {file_path, duration_seconds, file_size_bytes}.
    """
    with _index_lock:
        index = _load_index()
        entry = index.get(recording_id)
        if not entry:
            return {"error": f"Recording '{recording_id}' not found"}
        if entry["status"] != "recording":
            return {"error": f"Recording '{recording_id}' is not active (status={entry['status']})"}

        pid = entry.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
                try:
                    os.kill(pid, 0)
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            except OSError:
                pass

        stopped_at = datetime.now(timezone.utc).isoformat()
        file_path  = entry["file_path"]
        file_size  = 0
        duration   = None

        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            pass

        if entry.get("started_at"):
            try:
                from datetime import datetime as _dt
                start = _dt.fromisoformat(entry["started_at"].replace("Z", "+00:00"))
                stop  = _dt.fromisoformat(stopped_at.replace("Z", "+00:00"))
                duration = round((stop - start).total_seconds(), 1)
            except Exception:
                pass

        entry["status"]           = "stopped"
        entry["stopped_at"]       = stopped_at
        entry["duration_seconds"] = duration
        entry["file_size_bytes"]  = file_size
        index[recording_id]       = entry
        _save_index(index)

    log.info("stop_recording: recording_id=%s duration=%s size=%d", recording_id, duration, file_size)
    return {
        "file_path":        file_path,
        "duration_seconds": duration,
        "file_size_bytes":  file_size,
    }


def list_recordings(vm_id: str = None) -> list:
    """
    List all recordings. If vm_id given, filter by that VM.
    """
    try:
        with _index_lock:
            index = _load_index()
        entries = list(index.values())
        if vm_id:
            entries = [e for e in entries if e.get("vm_id") == vm_id]
        entries.sort(key=lambda e: e.get("started_at", ""), reverse=True)
        return entries
    except Exception as e:
        log.error("list_recordings: %s", e)
        return []


def get_recording(recording_id: str) -> dict:
    """Return metadata for a single recording."""
    try:
        with _index_lock:
            index = _load_index()
        entry = index.get(recording_id)
        if not entry:
            return {"error": f"Recording '{recording_id}' not found"}
        return dict(entry)
    except Exception as e:
        log.error("get_recording(%s): %s", recording_id, e)
        return {"error": str(e)}


def delete_recording(recording_id: str) -> dict:
    """Delete recording file and remove from index."""
    with _index_lock:
        index = _load_index()
        entry = index.get(recording_id)
        if not entry:
            return {"error": f"Recording '{recording_id}' not found"}

        if entry["status"] == "recording":
            pid = entry.get("pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        file_path = entry.get("file_path", "")
        deleted_file = False
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_file = True
            except Exception as e:
                log.warning("delete_recording: could not remove file %s: %s", file_path, e)

        del index[recording_id]
        _save_index(index)

    log.info("delete_recording: recording_id=%s file_deleted=%s", recording_id, deleted_file)
    return {"deleted": True, "file_deleted": deleted_file, "recording_id": recording_id}


def is_recording(vm_id: str) -> bool:
    """Return True if the given VM has an active recording."""
    try:
        with _index_lock:
            index = _load_index()
        for entry in index.values():
            if entry.get("vm_id") == vm_id and entry.get("status") == "recording":
                pid = entry.get("pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        return True
                    except OSError:
                        pass
        return False
    except Exception as e:
        log.error("is_recording(%s): %s", vm_id, e)
        return False






