"""ankavm audit-log retention policy + JSONL rotation.

The audit log (`/var/log/ankavm/audit_chain.jsonl`), runbook history
(`/var/lib/ankavm/runbook_history.jsonl`), and bulk-VM audit
(`/var/lib/ankavm/bulk_audit.jsonl`) all grow without bound until this
module trims them. Default policy retains 90 days of entries with a
hard size cap of 200 MB per file.

State: /var/lib/ankavm/audit_retention.json (policy settings only)
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("ankavm.audit_retention")
_POLICY_PATH = Path("/var/lib/ankavm/audit_retention.json")
_LOCK = threading.Lock()

DEFAULT_POLICY = {
    "enabled": True,
    "retention_days": 90,
    "max_file_mb": 200,
    "files": [
        "/var/log/ankavm/audit_chain.jsonl",
        "/var/lib/ankavm/runbook_history.jsonl",
        "/var/lib/ankavm/bulk_audit.jsonl",
    ],
    "compress_rotated": True,
}


def _load() -> dict:
    if not _POLICY_PATH.exists():
        return dict(DEFAULT_POLICY)
    try:
        return {**DEFAULT_POLICY, **json.loads(_POLICY_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULT_POLICY)


def _save(d: dict) -> None:
    _POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _POLICY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, _POLICY_PATH)


def get_policy() -> dict:
    return _load()


def set_policy(patch: dict) -> dict:
    with _LOCK:
        p = _load()
        for k in ("enabled", "retention_days", "max_file_mb",
                  "files", "compress_rotated"):
            if k in patch:
                p[k] = patch[k]
        _save(p)
    return p


def run_rotation_pass() -> dict:
    """Apply the retention policy to all tracked files. Returns a summary
    of bytes trimmed + entries removed per file."""
    policy = _load()
    if not policy.get("enabled", True):
        return {"ok": True, "skipped": "policy disabled"}
    cutoff = time.time() - policy["retention_days"] * 86400
    max_bytes = policy["max_file_mb"] * 1024 * 1024
    summary = []
    for path in policy["files"]:
        p = Path(path)
        if not p.exists():
            continue
        try:
            before = p.stat().st_size
            kept_lines = []
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("ts") or entry.get("timestamp")
                    if isinstance(ts, str):
                        try:
                            ts = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
                        except Exception:
                            ts = time.time()
                    if isinstance(ts, (int, float)) and ts < cutoff:
                        continue
                except Exception:
                    pass
                kept_lines.append(line)
            new_body = "\n".join(kept_lines) + ("\n" if kept_lines else "")
            if len(new_body.encode("utf-8")) > max_bytes:
                approx_chars = max_bytes
                new_body = new_body[-approx_chars:]
                nl = new_body.find("\n")
                if nl > 0:
                    new_body = new_body[nl + 1:]
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(new_body, encoding="utf-8")
            os.replace(tmp, p)
            after = p.stat().st_size
            summary.append({"file": str(p), "before": before, "after": after,
                            "bytes_trimmed": before - after})
        except Exception as e:
            log.warning("rotation failed for %s: %s", p, e)
            summary.append({"file": str(p), "error": str(e)})
    return {"ok": True, "summary": summary, "cutoff_ts": cutoff}






