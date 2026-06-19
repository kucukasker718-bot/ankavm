"""
ankavm v2.7.0 Flask Blueprint
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Starts the app.py modularization the external reviewer asked for. The
v2.7.0 enterprise endpoints (Confidential VM extensions, Runbook Executor,
Cluster Federation) live here instead of growing app.py further.

Registered from app.py:
    from bp_v270 import bp_v270, init_bp_v270
    init_bp_v270(confidential_vm, runbook_exec, federation_mgr,
                require_auth=require_auth, require_role=require_role,
                ok=ok, err=err)
    app.register_blueprint(bp_v270)

This keeps the decorators (`require_auth`, `require_role`) and the response
helpers (`ok`, `err`) on the app side without forcing this module to import
the giant app.py.
"""
from __future__ import annotations
import hashlib
import os
import time
from flask import Blueprint, request

try:
    from . import security_utils as _sec
except ImportError:
    import security_utils as _sec

bp_v270 = Blueprint("v270", __name__)

# SEC-023: force-run requires a fresh confirm_token derived from the runbook
# id + a server-side rotation key. Cached for 60s so the operator confirms
# once per minute, not per call.
_FORCE_CONFIRM_TTL = 60
_FORCE_CONFIRM_KEY = os.environ.get(
    "ankavm_FORCE_CONFIRM_KEY",
    "ankavm-force-confirm-rotates-on-restart",
)


def _force_token(rb_id: str) -> str:
    bucket = int(time.time() // _FORCE_CONFIRM_TTL)
    raw = f"{rb_id}|{bucket}|{_FORCE_CONFIRM_KEY}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]

# Late-bound dependencies, wired by init_bp_v270 from app.py
_cvm = None
_rbx = None
_fed = None
_require_auth = lambda fn: fn        # no-op until wired (would 401 on a real route)
_require_role = lambda *roles: (lambda fn: fn)
_ok = None
_err = None


def init_bp_v270(confidential_vm, runbook_exec, federation_mgr,
                 require_auth, require_role, ok, err):
    """Wire late-bound dependencies. Call before app.register_blueprint."""
    global _cvm, _rbx, _fed, _require_auth, _require_role, _ok, _err
    _cvm = confidential_vm
    _rbx = runbook_exec
    _fed = federation_mgr
    _require_auth = require_auth
    _require_role = require_role
    _ok = ok
    _err = err
    _register_routes()


def _register_routes():
    # â”€â”€ Confidential VM extensions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @bp_v270.route("/api/v2/confidential-vm/vms/<vm_id>/vtpm", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_cvm_vtpm(vm_id):
        if not _cvm:
            return _err("modÃ¼l yok", 503)
        d = request.get_json(silent=True) or {}
        try:
            return _ok(**_cvm.set_vtpm(vm_id, bool(d.get("enabled", True))))
        except Exception as e:
            return _err(e, 400)

    @bp_v270.route("/api/v2/confidential-vm/vms/<vm_id>/secure-boot", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_cvm_sb(vm_id):
        if not _cvm:
            return _err("modÃ¼l yok", 503)
        d = request.get_json(silent=True) or {}
        try:
            return _ok(**_cvm.set_secure_boot(vm_id, bool(d.get("enabled", True))))
        except Exception as e:
            return _err(e, 400)

    @bp_v270.route("/api/v2/confidential-vm/vms/<vm_id>/attest", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_cvm_attest(vm_id):
        if not _cvm:
            return _err("modÃ¼l yok", 503)
        try:
            return _ok(**_cvm.capture_attestation(vm_id))
        except Exception as e:
            return _err(e, 400)

    # â”€â”€ Runbook Executor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @bp_v270.route("/api/v2/runbooks", methods=["GET"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_rb_list():
        if not _rbx:
            return _ok(runbooks=[])
        return _ok(runbooks=_rbx.list_runbooks())

    @bp_v270.route("/api/v2/runbooks", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_rb_upsert():
        if not _rbx:
            return _err("modÃ¼l yok", 503)
        try:
            return _ok(runbook=_rbx.upsert_runbook(request.get_json(silent=True) or {}))
        except Exception as e:
            return _err(e, 400)

    @bp_v270.route("/api/v2/runbooks/<rb_id>", methods=["DELETE"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_rb_delete(rb_id):
        if not _rbx:
            return _err("modÃ¼l yok", 503)
        return _ok(removed=_rbx.delete_runbook(rb_id))

    @bp_v270.route("/api/v2/runbooks/<rb_id>/run", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_rb_run(rb_id):
        if not _rbx:
            return _err("modÃ¼l yok", 503)
        d = request.get_json(silent=True) or {}
        force = bool(d.get("force"))
        # SEC-023: force=true bypasses cooldown+quota â€” require a server-side
        # confirm_token rotating every 60s. Client first POSTs without
        # confirm_token to obtain the expected one, then re-POSTs with it.
        if force:
            expected = _force_token(rb_id)
            if d.get("confirm_token") != expected:
                return _err({
                    "requires_confirmation": True,
                    "confirm_token": expected,
                    "ttl_sec": _FORCE_CONFIRM_TTL,
                    "message": "force=true requires confirm_token (rotates every 60s)",
                }, 409)
        return _ok(**_rbx.execute_runbook(rb_id, d.get("ctx"), force=force))

    @bp_v270.route("/api/v2/runbooks/history", methods=["GET"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_rb_history():
        if not _rbx:
            return _ok(history=[])
        try:
            limit = int(request.args.get("limit", 100))
        except Exception:
            limit = 100
        return _ok(history=_rbx.history(limit=limit))

    # â”€â”€ Cluster Federation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @bp_v270.route("/api/v2/federation/members", methods=["GET"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_fed_list():
        if not _fed:
            return _ok(members=[])
        members = []
        for m in _fed.list_members():
            m2 = dict(m)
            m2["token"] = "***"
            members.append(m2)
        return _ok(members=members)

    @bp_v270.route("/api/v2/federation/members", methods=["POST"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_fed_add():
        if not _fed:
            return _err("modÃ¼l yok", 503)
        d = request.get_json(silent=True) or {}
        # SEC-021: pre-validate URL here so the API returns a clean 400 instead
        # of a 500 from a deep ValueError chain. add_member() will re-validate.
        try:
            _sec.validate_external_url(
                d.get("url", ""),
                allow_loopback=os.environ.get("ankavm_FEDERATION_ALLOW_INSECURE") == "1",
                allow_http=os.environ.get("ankavm_FEDERATION_ALLOW_INSECURE") == "1",
            )
        except _sec.SecurityValidationError as e:
            return _err(str(e), 400)
        try:
            m = _fed.add_member(
                url=d.get("url", ""), token=d.get("token", ""),
                label=d.get("label", ""), region=d.get("region", ""),
                role=d.get("role", "follower"),
                verify_tls=bool(d.get("verify_tls", True)),
            )
            m = dict(m); m["token"] = "***"
            return _ok(member=m)
        except Exception as e:
            return _err(e, 400)

    @bp_v270.route("/api/v2/federation/members/<member_id>", methods=["DELETE", "PATCH"])
    @_require_auth
    @_require_role("admin", "administrator")
    def api_fed_mut(member_id):
        if not _fed:
            return _err("modÃ¼l yok", 503)
        if request.method == "DELETE":
            return _ok(removed=_fed.remove_member(member_id))
        d = request.get_json(silent=True) or {}
        m = _fed.update_member(member_id, d)
        if not m:
            return _err("not found", 404)
        m = dict(m); m["token"] = "***"
        return _ok(member=m)

    @bp_v270.route("/api/v2/federation/health", methods=["GET"])
    @_require_auth
    @_require_role("admin", "administrator", "operator")
    def api_fed_health():
        if not _fed:
            return _ok(members=[])
        return _ok(health=_fed.health(request.args.get("member_id")))

    @bp_v270.route("/api/v2/federation/inventory/vms", methods=["GET"])
    @_require_auth
    @_require_role("admin", "administrator", "operator")
    def api_fed_inv():
        if not _fed:
            return _ok(total=0, members=[], vms=[])
        return _ok(**_fed.inventory_vms())






