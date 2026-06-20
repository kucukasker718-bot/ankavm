"""
ankavm Managed Cluster Federation
──────────────────────────────────
Federate multiple ankavm nodes into a single control plane.

State:
  /etc/ankavm/federation.json    member roster (id, url, token, region, role)
  /var/lib/ankavm/federation_cache.json   last-seen status per member

A federation member is another ankavm controller reachable over HTTPS.
The local node calls each member's REST API (with the federation token)
to enumerate VMs, hosts, and alerts. Bulk actions iterate over members in
parallel.

This module is read-mostly. Writes (start/stop/create) are forwarded to
the target member's own controller, so audit logs stay local to where the
VM lives.
"""
from __future__ import annotations
import concurrent.futures as _cf
import json
import logging
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

try:
    from . import security_utils as _sec
except ImportError:
    import security_utils as _sec

log = logging.getLogger("ankavm.federation")

_ROSTER = Path("/etc/ankavm/federation.json")
_CACHE = Path("/var/lib/ankavm/federation_cache.json")
_LOCK = threading.Lock()
_DEFAULT_TIMEOUT = 6

# SEC-019: federation members must be https. Operators may set this env var
# to allow loopback URLs during local testing only.
_ALLOW_INSECURE = os.environ.get("ankavm_FEDERATION_ALLOW_INSECURE") == "1"


def _ensure():
    try:
        _ROSTER.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _load_roster() -> dict:
    _ensure()
    if not _ROSTER.exists():
        return {"members": [], "local_id": _local_id(), "updated_at": 0}
    try:
        return json.loads(_ROSTER.read_text(encoding="utf-8"))
    except Exception:
        return {"members": [], "local_id": _local_id(), "updated_at": 0}


def _save_roster(d: dict):
    _ensure()
    d["updated_at"] = time.time()
    tmp = _ROSTER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, _ROSTER)


def _local_id() -> str:
    try:
        return f"local-{socket.gethostname()}"
    except Exception:
        return "local"


def list_members() -> list:
    return _load_roster().get("members", [])


def add_member(url: str, token: str, label: str = "",
               region: str = "", role: str = "follower",
               verify_tls: bool = True) -> dict:
    if not url or not token:
        raise ValueError("url and token are required")
    if role not in ("leader", "follower", "observer"):
        raise ValueError("role must be leader|follower|observer")
    # SEC-019 + SEC-021: validate URL format and block private/loopback IPs
    # unless _ALLOW_INSECURE is set. Also normalizes the URL.
    safe_url = _sec.validate_external_url(
        url,
        allow_loopback=_ALLOW_INSECURE,
        allow_http=_ALLOW_INSECURE,
    )
    # SEC-019: TLS verification cannot be disabled in production. Operators
    # who really need a local cluster bypass must set ankavm_FEDERATION_ALLOW_INSECURE=1.
    if not verify_tls and not _ALLOW_INSECURE:
        log.warning("ignoring verify_tls=False (set ankavm_FEDERATION_ALLOW_INSECURE=1 to override)")
        verify_tls = True
    member = {
        "id": str(uuid.uuid4()),
        "url": safe_url.rstrip("/"),
        "token": token,
        "label": label or safe_url,
        "region": region,
        "role": role,
        "verify_tls": bool(verify_tls),
        "added_at": time.time(),
    }
    with _LOCK:
        d = _load_roster()
        d.setdefault("members", []).append(member)
        _save_roster(d)
    log.info("federation member added: %s (%s)", member["id"], member["label"])
    return member


def remove_member(member_id: str) -> bool:
    with _LOCK:
        d = _load_roster()
        members = d.get("members", [])
        new = [m for m in members if m.get("id") != member_id]
        if len(new) == len(members):
            return False
        d["members"] = new
        _save_roster(d)
    return True


def update_member(member_id: str, patch: dict) -> dict | None:
    with _LOCK:
        d = _load_roster()
        for m in d.get("members", []):
            if m.get("id") == member_id:
                for k, v in (patch or {}).items():
                    if k not in ("url", "token", "label", "region", "role", "verify_tls"):
                        continue
                    # SEC-019: validate URL changes through the same guard as add_member.
                    if k == "url":
                        v = _sec.validate_external_url(
                            v,
                            allow_loopback=_ALLOW_INSECURE,
                            allow_http=_ALLOW_INSECURE,
                        ).rstrip("/")
                    if k == "verify_tls" and not bool(v) and not _ALLOW_INSECURE:
                        log.warning("update_member: ignored verify_tls=False")
                        v = True
                    m[k] = v
                _save_roster(d)
                return m
    return None


def _request(member: dict, path: str, method: str = "GET",
             payload: dict | None = None, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    url = member["url"] + path
    data = None
    headers = {"Authorization": f"Bearer {member['token']}",
               "Accept": "application/json",
               "User-Agent": "ankavm-Federation/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl.create_default_context()
    if not member.get("verify_tls", True):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read().decode("utf-8", "replace")
        try:
            return {"status": resp.status, "json": json.loads(body)}
        except Exception:
            return {"status": resp.status, "text": body}


def health(member_id: str | None = None) -> list:
    members = [m for m in list_members()
               if member_id is None or m.get("id") == member_id]
    out = []
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_check_one, m): m for m in members}
        for fut in _cf.as_completed(futs):
            out.append(fut.result())
    _store_cache({"health": out, "ts": time.time()})
    return out


def _check_one(m: dict) -> dict:
    t0 = time.time()
    try:
        r = _request(m, "/api/health", timeout=4)
        latency_ms = int((time.time() - t0) * 1000)
        return {"id": m["id"], "label": m.get("label"), "ok": True,
                "status": r.get("status"), "latency_ms": latency_ms,
                "data": r.get("json", r.get("text"))}
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return {"id": m["id"], "label": m.get("label"), "ok": False,
                "error": str(e), "latency_ms": int((time.time() - t0) * 1000)}


def inventory_vms() -> dict:
    """Aggregate /api/vms across all members."""
    members = list_members()
    agg = {"total": 0, "members": [], "vms": []}
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_request, m, "/api/vms"): m for m in members}
        for fut in _cf.as_completed(futs):
            m = futs[fut]
            try:
                r = fut.result()
                vms = (r.get("json") or {}).get("vms", []) if isinstance(r.get("json"), dict) else []
                for v in vms:
                    v["_member_id"] = m["id"]
                    v["_member_label"] = m.get("label")
                    v["_region"] = m.get("region")
                agg["vms"].extend(vms)
                agg["members"].append({"id": m["id"], "label": m.get("label"),
                                       "count": len(vms), "ok": True})
            except Exception as e:
                agg["members"].append({"id": m["id"], "label": m.get("label"),
                                       "count": 0, "ok": False, "error": str(e)})
    agg["total"] = len(agg["vms"])
    _store_cache({"inventory": agg, "ts": time.time()})
    return agg


def forward(member_id: str, path: str, method: str = "GET",
            payload: dict | None = None) -> dict:
    """Forward an API call to a single member. The member's own RBAC and
    audit log enforce the action — this node only proxies.

    SEC-020: path is restricted to the federation forward allowlist.
    """
    try:
        path = _sec.validate_forward_path(path)
    except _sec.SecurityValidationError as e:
        return {"ok": False, "member_id": member_id, "error": str(e)}
    for m in list_members():
        if m.get("id") == member_id:
            try:
                r = _request(m, path, method=method, payload=payload, timeout=20)
                return {"ok": True, "member_id": member_id, **r}
            except Exception as e:
                return {"ok": False, "member_id": member_id, "error": str(e)}
    return {"ok": False, "error": "member not found"}


def bulk_action(member_ids: list, path: str, method: str = "POST",
                payload: dict | None = None) -> list:
    """Run the same call against many members in parallel.

    SEC-020: path is restricted to the federation forward allowlist.
    """
    try:
        path = _sec.validate_forward_path(path)
    except _sec.SecurityValidationError as e:
        return [{"ok": False, "member_id": mid, "error": str(e)} for mid in member_ids]
    members = [m for m in list_members() if m["id"] in set(member_ids)]
    out = []
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_request, m, path, method, payload, 30): m for m in members}
        for fut in _cf.as_completed(futs):
            m = futs[fut]
            try:
                r = fut.result()
                out.append({"member_id": m["id"], "ok": True, **r})
            except Exception as e:
                out.append({"member_id": m["id"], "ok": False, "error": str(e)})
    return out


def _store_cache(d: dict):
    try:
        _ensure()
        tmp = _CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, default=str), encoding="utf-8")
        os.replace(tmp, _CACHE)
    except Exception:
        pass


def get_cache() -> dict:
    if not _CACHE.exists():
        return {}
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}






