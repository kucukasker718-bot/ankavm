"""
Hash-chained audit log — each line links to previous via sha256.
Tamper-evident: any line modification invalidates every subsequent hash.
"""
import json
import time
import hashlib
import logging
import threading
from pathlib import Path

log = logging.getLogger("audit_chain")

DATA_DIR = Path("/var/lib/ankavm")
CHAIN_PATH = DATA_DIR / "audit_chain.jsonl"

_lock = threading.Lock()
GENESIS = "0" * 64


def _ensure():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not CHAIN_PATH.exists():
            CHAIN_PATH.touch()
    except Exception as e:
        log.warning("audit_chain ensure: %s", e)


def _last_hash() -> str:
    try:
        _ensure()
        if not CHAIN_PATH.exists():
            return GENESIS
        last = None
        with CHAIN_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
        if not last:
            return GENESIS
        return json.loads(last).get("hash", GENESIS)
    except Exception as e:
        log.error("_last_hash: %s", e)
        return GENESIS


def _hash_entry(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def append_event(event: str, user: str = "system", ip: str = "",
                 details: dict = None) -> dict:
    try:
        _ensure()
        details = details or {}
        with _lock:
            prev = _last_hash()
            payload = {
                "ts": time.time(),
                "event": event,
                "user": user,
                "ip": ip,
                "details": details,
                "prev_hash": prev,
            }
            h = _hash_entry(prev, payload)
            payload["hash"] = h
            with CHAIN_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return {"ok": True, "hash": h}
    except Exception as e:
        log.error("append_event: %s", e)
        return {"ok": False, "error": str(e)}


def verify_chain() -> dict:
    try:
        _ensure()
        prev = GENESIS
        count = 0
        bad = []
        with CHAIN_PATH.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    rec = json.loads(line)
                except Exception:
                    bad.append({"line": idx, "reason": "invalid json"})
                    continue
                stored = rec.get("hash")
                stored_prev = rec.get("prev_hash")
                if stored_prev != prev:
                    bad.append({"line": idx, "reason": "prev_hash mismatch"})
                recompute = _hash_entry(prev, {k: v for k, v in rec.items() if k != "hash"})
                if recompute != stored:
                    bad.append({"line": idx, "reason": "hash mismatch"})
                prev = stored or prev
        return {"ok": len(bad) == 0, "events": count, "broken": bad}
    except Exception as e:
        log.error("verify_chain: %s", e)
        return {"ok": False, "error": str(e), "events": 0, "broken": []}


def get_events(limit: int = 100, filter_user: str = None,
               filter_event: str = None) -> list:
    try:
        _ensure()
        out = []
        with CHAIN_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if filter_user and rec.get("user") != filter_user:
                continue
            if filter_event and filter_event not in (rec.get("event") or ""):
                continue
            out.append(rec)
            if len(out) >= int(limit):
                break
        return out
    except Exception as e:
        log.error("get_events: %s", e)
        return []


def get_stats() -> dict:
    try:
        _ensure()
        users = {}
        events = {}
        count = 0
        with CHAIN_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                count += 1
                users[rec.get("user", "?")] = users.get(rec.get("user", "?"), 0) + 1
                events[rec.get("event", "?")] = events.get(rec.get("event", "?"), 0) + 1
        return {"total": count, "by_user": users, "by_event": events,
                "file_size": CHAIN_PATH.stat().st_size if CHAIN_PATH.exists() else 0}
    except Exception as e:
        log.error("get_stats: %s", e)
        return {"total": 0, "by_user": {}, "by_event": {}, "file_size": 0}






