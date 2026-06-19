"""
ankavm Session Recorder
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SSH/VNC/console session recording (asciinema benzeri).
TÃ¼m I/O kayÄ±t + audit + replay.

API:
    start_recording(session_id, user, vm, type) -> dict
    write(session_id, data, direction)        ('in'/'out')
    stop_recording(session_id) -> dict
    list_recordings(filter_user=None) -> list
    get_recording(rec_id) -> bytes  (asciinema cast format)
    delete_recording(rec_id) -> bool
"""

import os, json, time, uuid, threading, logging
from pathlib import Path

log = logging.getLogger("session_recorder")

_REC_DIR  = Path("/var/lib/ankavm/recordings")
_INDEX    = _REC_DIR / "index.json"
_LOCK     = threading.Lock()
_ACTIVE   = {}            # session_id â†’ {path, fp, start_ts, meta}


def _load_index() -> list:
    if _INDEX.exists():
        try:
            return json.loads(_INDEX.read_text())
        except Exception:
            pass
    return []


def _save_index(recs: list):
    _REC_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX.write_text(json.dumps(recs, indent=2, ensure_ascii=False))


def start_recording(session_id: str = None, user: str = "anonymous",
                    vm: str = "", session_type: str = "ssh",
                    cols: int = 120, rows: int = 30) -> dict:
    """asciinema v2 cast format start."""
    sid = session_id or uuid.uuid4().hex[:16]
    _REC_DIR.mkdir(parents=True, exist_ok=True)
    path = _REC_DIR / f"{sid}.cast"

    header = {
        "version":   2,
        "width":     cols,
        "height":    rows,
        "timestamp": int(time.time()),
        "title":     f"{session_type}:{user}@{vm or 'host'}",
        "env":       {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
    }

    fp = open(path, "w", encoding="utf-8", buffering=1)
    fp.write(json.dumps(header) + "\n")

    meta = {
        "id":       sid,
        "user":     user,
        "vm":       vm,
        "type":     session_type,
        "path":     str(path),
        "started":  int(time.time()),
        "ended":    None,
        "size":     0,
        "events":   0,
    }
    with _LOCK:
        _ACTIVE[sid] = {"fp": fp, "start": time.time(), "meta": meta, "events": 0}
        recs = _load_index()
        recs.append(meta)
        _save_index(recs)

    return meta


def write(session_id: str, data: str, direction: str = "o") -> None:
    """
    direction: 'o' (output, terminal'e yazÄ±lan) | 'i' (input, kullanÄ±cÄ±nÄ±n tuÅŸladÄ±ÄŸÄ±)
    """
    if not data:
        return
    with _LOCK:
        sess = _ACTIVE.get(session_id)
        if not sess:
            return
    try:
        elapsed = round(time.time() - sess["start"], 6)
        event = [elapsed, direction, data]
        sess["fp"].write(json.dumps(event) + "\n")
        sess["events"] += 1
    except Exception as e:
        log.warning("session write hatasÄ±: %s", e)


def stop_recording(session_id: str) -> dict:
    with _LOCK:
        sess = _ACTIVE.pop(session_id, None)
    if not sess:
        return {"ok": False, "error": "Session bulunamadÄ±"}
    try:
        sess["fp"].flush()
        sess["fp"].close()
    except Exception:
        pass

    meta = sess["meta"]
    meta["ended"]  = int(time.time())
    meta["events"] = sess["events"]
    try:
        meta["size"] = Path(meta["path"]).stat().st_size
    except Exception:
        pass

    with _LOCK:
        recs = _load_index()
        for i, r in enumerate(recs):
            if r["id"] == session_id:
                recs[i] = meta
                break
        _save_index(recs)

    return meta


def list_recordings(filter_user: str = None, filter_vm: str = None,
                    limit: int = 200) -> list:
    recs = _load_index()
    if filter_user:
        recs = [r for r in recs if r.get("user") == filter_user]
    if filter_vm:
        recs = [r for r in recs if r.get("vm") == filter_vm]
    return sorted(recs, key=lambda r: r.get("started", 0), reverse=True)[:limit]


def get_recording(rec_id: str) -> bytes:
    """Cast dosyasÄ±nÄ± byte olarak dÃ¶ndÃ¼r (download iÃ§in)."""
    recs = _load_index()
    rec  = next((r for r in recs if r["id"] == rec_id), None)
    if not rec:
        raise KeyError(rec_id)
    return Path(rec["path"]).read_bytes()


def delete_recording(rec_id: str) -> bool:
    with _LOCK:
        recs = _load_index()
        rec  = next((r for r in recs if r["id"] == rec_id), None)
        if not rec:
            return False
        try:
            Path(rec["path"]).unlink()
        except Exception:
            pass
        new = [r for r in recs if r["id"] != rec_id]
        _save_index(new)
    return True


def cleanup_old(days: int = 90) -> int:
    """Eski kayÄ±tlarÄ± temizle."""
    cutoff = time.time() - (days * 86400)
    deleted = 0
    for r in list_recordings(limit=10000):
        if r.get("started", 0) < cutoff:
            if delete_recording(r["id"]):
                deleted += 1
    return deleted


def stats() -> dict:
    recs = _load_index()
    total_size = sum(r.get("size", 0) for r in recs)
    return {
        "count":       len(recs),
        "active":      len(_ACTIVE),
        "total_bytes": total_size,
        "total_mb":    round(total_size / (1024 * 1024), 2),
        "directory":   str(_REC_DIR),
    }






