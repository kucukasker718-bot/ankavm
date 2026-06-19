"""
ankavm 2FA Recovery Codes
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Single-use backup codes for TOTP/2FA account recovery.
Codes: 8 groups of 4 chars (XXXX-XXXX format), SHA-256 hashed.
State: /var/lib/ankavm/recovery_codes.json (hashed, per-user)
"""

import hashlib
import json
import logging
import os
import secrets
import threading
import time

log = logging.getLogger("ankavm.recovery_codes")

DATA_PATH = "/var/lib/ankavm/recovery_codes.json"
_lock     = threading.Lock()


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        if os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error("_load: %s", e)
    return {}


def _save(data: dict):
    try:
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        tmp = DATA_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DATA_PATH)
    except Exception as e:
        log.error("_save: %s", e)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

def _make_salt() -> str:
    return secrets.token_hex(16)


def _hash_code(plain: str, salt: str) -> str:
    return hashlib.sha256((salt + plain.upper().replace("-", "")).encode()).hexdigest()


def _format_code(raw_hex: str) -> str:
    """Convert 8-char hex slice to XXXX-XXXX uppercase."""
    chunk = raw_hex[:8].upper()
    return f"{chunk[:4]}-{chunk[4:]}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_codes(username: str, count: int = 8) -> list:
    """
    Generate `count` single-use recovery codes for `username`.
    Replaces any existing codes. Returns plaintext codes (shown once).
    """
    salt      = _make_salt()
    plaintext = []
    hashed    = []

    for _ in range(count):
        raw  = secrets.token_hex(4)
        code = _format_code(raw)
        plaintext.append(code)
        hashed.append({
            "hash":    _hash_code(code, salt),
            "used":    False,
            "used_at": None,
        })

    entry = {
        "salt":         salt,
        "codes":        hashed,
        "generated_at": time.time(),
    }

    with _lock:
        data = _load()
        data[username] = entry
        _save(data)

    log.info("generate_codes: %d codes generated for %s", count, username)
    return plaintext


def verify_code(username: str, code: str) -> bool:
    """
    Verify a recovery code. If valid and unused, mark as used and return True.
    Returns False if code not found, already used, or user has no codes.
    """
    with _lock:
        data  = _load()
        entry = data.get(username)
        if not entry:
            return False

        salt     = entry.get("salt", "")
        needle   = _hash_code(code, salt)
        matched  = False

        for record in entry.get("codes", []):
            if not record.get("used") and record.get("hash") == needle:
                record["used"]    = True
                record["used_at"] = time.time()
                matched           = True
                break

        if matched:
            _save(data)
            log.info("verify_code: code accepted for %s", username)

    return matched


def has_codes(username: str) -> bool:
    """Return True if user has at least one unused recovery code."""
    try:
        with _lock:
            data = _load()
        entry = data.get(username)
        if not entry:
            return False
        return any(not r.get("used") for r in entry.get("codes", []))
    except Exception as e:
        log.error("has_codes(%s): %s", username, e)
        return False


def remaining_count(username: str) -> int:
    """Return number of unused recovery codes for user."""
    try:
        with _lock:
            data = _load()
        entry = data.get(username)
        if not entry:
            return 0
        return sum(1 for r in entry.get("codes", []) if not r.get("used"))
    except Exception as e:
        log.error("remaining_count(%s): %s", username, e)
        return 0


def revoke_all(username: str) -> dict:
    """Delete all recovery codes for user."""
    with _lock:
        data = _load()
        if username not in data:
            return {"revoked": False, "error": f"No codes found for '{username}'"}
        del data[username]
        _save(data)
    log.info("revoke_all: codes revoked for %s", username)
    return {"revoked": True, "username": username}


def get_status(username: str) -> dict:
    """Return {has_codes, count, generated_at} for user."""
    try:
        with _lock:
            data = _load()
        entry = data.get(username)
        if not entry:
            return {"has_codes": False, "count": 0, "generated_at": None}
        count = sum(1 for r in entry.get("codes", []) if not r.get("used"))
        return {
            "has_codes":    count > 0,
            "count":        count,
            "generated_at": entry.get("generated_at"),
        }
    except Exception as e:
        log.error("get_status(%s): %s", username, e)
        return {"has_codes": False, "count": 0, "generated_at": None, "error": str(e)}






