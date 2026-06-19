"""
ankavm MFA Enforcement per Role
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Enforce mandatory 2FA for selected roles.
Default policy: admin = required, operator = optional, vm-user = optional.
Login flow checks this â€” if role policy=required and user has no TOTP secret,
reject login (force enrollment).

Config: /var/lib/ankavm/mfa_policy.json
"""
from __future__ import annotations
import json, logging
from pathlib import Path

log = logging.getLogger("mfa_enforcement")
_CFG = Path("/var/lib/ankavm/mfa_policy.json")

DEFAULT_POLICY = {
    "admin":         "required",
    "administrator": "required",
    "operator":      "optional",
    "vm-user":       "optional",
}


def _load() -> dict:
    try:
        if _CFG.exists():
            data = json.loads(_CFG.read_text(encoding="utf-8"))
            # Merge with defaults (preserves new roles)
            merged = dict(DEFAULT_POLICY)
            merged.update(data)
            return merged
    except Exception:
        pass
    return dict(DEFAULT_POLICY)


def _save(d: dict):
    _CFG.parent.mkdir(parents=True, exist_ok=True)
    _CFG.write_text(json.dumps(d, indent=2), encoding="utf-8")


def get_policy() -> dict:
    """Return {role: 'required'|'optional'|'disabled'}."""
    return _load()


def set_role_policy(role: str, policy: str) -> dict:
    if policy not in ("required", "optional", "disabled"):
        return {"ok": False, "error": "policy must be required/optional/disabled"}
    d = _load()
    d[role] = policy
    _save(d)
    log.info("MFA policy: %s = %s", role, policy)
    return {"ok": True, "role": role, "policy": policy}


def is_required(role: str) -> bool:
    return _load().get(role, "optional") == "required"


def check_login_allowed(role: str, has_totp_secret: bool) -> dict:
    """Return {allowed: bool, reason: str, force_enroll: bool}"""
    pol = _load().get(role, "optional")
    if pol == "required" and not has_totp_secret:
        return {"allowed": False,
                "force_enroll": True,
                "reason": f"2FA zorunlu ({role} rolÃ¼) â€” TOTP kurulumu yapÄ±n"}
    return {"allowed": True, "force_enroll": False, "reason": ""}






