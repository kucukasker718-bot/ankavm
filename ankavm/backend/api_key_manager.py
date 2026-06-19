"""
api_key_manager.py - API anahtar yÃ¶netimi.
Veri: /var/lib/ankavm/api_keys.json
"""

import json
import hashlib
import hmac
import secrets
import uuid
import threading
import time
import os
import logging

log = logging.getLogger("ankavm.apikeys")

DATA_PATH = "/var/lib/ankavm/api_keys.json"
_lock     = threading.Lock()


# ---------------------------------------------------------------------------
# Dosya I/O
# ---------------------------------------------------------------------------

def _load():
    """JSON dosyasÄ±nÄ± yÃ¼kler; yoksa boÅŸ dict dÃ¶ndÃ¼rÃ¼r."""
    try:
        if os.path.exists(DATA_PATH):
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error("_load hatasÄ±: %s", e)
    return {}


def _save(data):
    """JSON dosyasÄ±nÄ± atomik yazar."""
    try:
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        tmp = DATA_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DATA_PATH)
    except Exception as e:
        log.error("_save hatasÄ±: %s", e)


def _get_pepper() -> bytes:
    """Server-side pepper â€” API key hash'lerini offline brute-force'a karÅŸÄ± korur."""
    pepper_file = "/etc/ankavm/api_key_pepper.bin"
    if os.path.exists(pepper_file):
        try:
            with open(pepper_file, "rb") as f:
                return f.read()
        except Exception:
            pass
    # Pepper yoksa oluÅŸtur ve kaydet
    pepper = secrets.token_bytes(32)
    try:
        os.makedirs("/etc/ankavm", exist_ok=True)
        with open(pepper_file, "wb") as f:
            f.write(pepper)
        os.chmod(pepper_file, 0o600)
    except Exception:
        pass
    return pepper

def _hash(key):
    """OXW-2026-019 fix: API key'i server-pepper HMAC-SHA256 ile hash'ler.
    Ã–nceki plain SHA-256 â†’ pepper'lÄ± HMAC ile deÄŸiÅŸtirildi.
    """
    return hmac.new(_get_pepper(), key.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# API Key iÅŸlemleri
# ---------------------------------------------------------------------------

def create_key(username, name, permissions=None, expires_days=None):
    """
    Yeni API key Ã¼retir ve kaydeder.
    DÃ¶ner: {"id": str, "key": "oxw_xxx", "name": str, "created_at": float}
    """
    try:
        raw_key   = "oxw_" + secrets.token_hex(32)
        key_id    = str(uuid.uuid4())
        key_hash  = _hash(raw_key)
        created   = time.time()
        expires   = (created + expires_days * 86400) if expires_days else None

        entry = {
            "id":          key_id,
            "name":        name,
            "username":    username,
            "key_hash":    key_hash,
            "permissions": permissions or [],
            "created_at":  created,
            "expires_at":  expires,
            "last_used":   None,
            "use_count":   0,
            "active":      True,
        }

        with _lock:
            data = _load()
            data[key_id] = entry
            _save(data)

        log.info("create_key: %s iÃ§in '%s' key oluÅŸturuldu.", username, name)
        return {
            "id":         key_id,
            "key":        raw_key,
            "name":       name,
            "created_at": created,
        }
    except Exception as e:
        log.error("create_key hatasÄ± (username=%s): %s", username, e)
        return {}


def validate_key(raw_key):
    """
    Ham key'i doÄŸrular.
    DÃ¶ner: {"username": str, "permissions": list, "key_id": str} veya None.
    """
    try:
        if not raw_key or not raw_key.startswith("oxw_"):
            return None
        key_hash = _hash(raw_key)
        now = time.time()

        with _lock:
            data = _load()
            for key_id, entry in data.items():
                # OXW-2026-019 fix: sabit-zamanlÄ± karÅŸÄ±laÅŸtÄ±rma (timing oracle Ã¶nleme)
                if not hmac.compare_digest(entry.get("key_hash", ""), key_hash):
                    continue
                if not entry.get("active", False):
                    return None
                if entry.get("expires_at") and now > entry["expires_at"]:
                    return None
                # KullanÄ±m istatistiklerini gÃ¼ncelle
                entry["last_used"] = now
                entry["use_count"] = entry.get("use_count", 0) + 1
                _save(data)
                return {
                    "username":    entry["username"],
                    "permissions": entry.get("permissions", []),
                    "key_id":      key_id,
                }
        return None
    except Exception as e:
        log.error("validate_key hatasÄ±: %s", e)
        return None


def revoke_key(key_id, username=None):
    """
    Key'i devre dÄ±ÅŸÄ± bÄ±rakÄ±r (active=False).
    username verilirse yetki kontrolÃ¼ yapÄ±lÄ±r.
    DÃ¶ner: bool
    """
    try:
        with _lock:
            data = _load()
            entry = data.get(key_id)
            if not entry:
                return False
            if username and entry.get("username") != username:
                log.warning("revoke_key: yetki reddi (key_id=%s, username=%s)", key_id, username)
                return False
            entry["active"] = False
            _save(data)
        log.info("revoke_key: %s devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±.", key_id)
        return True
    except Exception as e:
        log.error("revoke_key hatasÄ± (key_id=%s): %s", key_id, e)
        return False


def delete_key(key_id):
    """
    Key'i kalÄ±cÄ± olarak siler.
    DÃ¶ner: bool
    """
    try:
        with _lock:
            data = _load()
            if key_id not in data:
                return False
            del data[key_id]
            _save(data)
        log.info("delete_key: %s silindi.", key_id)
        return True
    except Exception as e:
        log.error("delete_key hatasÄ± (key_id=%s): %s", key_id, e)
        return False


def list_keys(username):
    """
    KullanÄ±cÄ±nÄ±n tÃ¼m key'lerini dÃ¶ndÃ¼rÃ¼r (key_hash gÃ¶sterilmez).
    DÃ¶ner: list of dict
    """
    try:
        with _lock:
            data = _load()
        result = []
        for key_id, entry in data.items():
            if entry.get("username") != username:
                continue
            safe = {k: v for k, v in entry.items() if k != "key_hash"}
            result.append(safe)
        return result
    except Exception as e:
        log.error("list_keys hatasÄ± (username=%s): %s", username, e)
        return []


def get_key(key_id):
    """
    Tek key bilgisi dÃ¶ndÃ¼rÃ¼r (key_hash gÃ¶sterilmez).
    DÃ¶ner: dict veya None
    """
    try:
        with _lock:
            data = _load()
        entry = data.get(key_id)
        if not entry:
            return None
        return {k: v for k, v in entry.items() if k != "key_hash"}
    except Exception as e:
        log.error("get_key hatasÄ± (key_id=%s): %s", key_id, e)
        return None






