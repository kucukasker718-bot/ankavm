"""
ankavm Lisans Yöneticisi
─────────────────────────
Lisans doğrulama sistemi.
"""
import os
import json
import hashlib
import logging
import time
import base64
from pathlib import Path

log = logging.getLogger("ankavm.license")

LICENSE_FILE       = "/var/lib/ankavm/license.json"
ACTIVATIONS_FILE   = "/var/lib/ankavm/license_activations.json"

# ── Runtime-assembled constants (not stored as literals) ──────────────────────

def _r(*parts):
    """Assemble string from base64 parts at runtime."""
    return b"".join(base64.b64decode(p) for p in parts).decode()

def _rb(*parts):
    """Assemble bytes from base64 parts at runtime."""
    return b"".join(base64.b64decode(p) for p in parts)

# Repo path — assembled at import time into module-level var
_LICENSE_REPO    = _r("U2hpbm5Bc3VraGE=", "L29wd2FyZS1saWNlbnNl")
_LICENSE_RAW_URL = _r(
    "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tLw==",
    "U2hpbm5Bc3VraGEvb3h3YXJlLWxpY2Vuc2U=",
    "L21haW4vLmxpY2Vuc2Vjb2Rlcw==",
)

# Passphrase — read from env first (production), fall back to assembled bytes
def _get_passphrase() -> bytes:
    env = os.environ.get("OXW_LICENSE_KEY", "")
    if env:
        return env.encode()
    # Assembled from 4 fragments, XOR'd with mask at runtime
    _m = 0x4F
    _f = [
        b'\x00\x178.=*b',
        b'\x03&,*!<*b',
        b'\x1c*,=*;b}',
        b"\x7f}{b\x1c'&!!\x0e<:$'.",
    ]
    return bytes(c ^ _m for seg in _f for c in seg)

_codes_cache: list = []
_cache_ts: float = 0.0
CACHE_TTL = 3600  # 1 saat


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        key_bytes = hashlib.sha256(_get_passphrase()).digest()
        key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(key)
    except Exception as e:
        log.warning("Fernet yüklenemedi: %s", e)
        return None


def _fetch_license_codes() -> list:
    """Lisans listesini uzak kaynaktan al, çöz ve önbelleğe al."""
    global _codes_cache, _cache_ts

    if _codes_cache and (time.time() - _cache_ts) < CACHE_TTL:
        return _codes_cache

    try:
        import urllib.request
        req = urllib.request.Request(
            _LICENSE_RAW_URL,
            headers={"User-Agent": "ankavm/2.1", "Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            encrypted_data = resp.read().strip()

        fernet = _get_fernet()
        if not fernet:
            log.error("Fernet başlatılamadı")
            return _codes_cache

        decrypted = fernet.decrypt(encrypted_data)
        codes = [line.strip() for line in decrypted.decode("utf-8").splitlines()
                 if line.strip() and line.strip().startswith("ankavm-")]

        _codes_cache = codes
        _cache_ts = time.time()
        log.info("Lisans listesi güncellendi: %d kod", len(codes))
        return codes

    except Exception as e:
        log.warning("Lisans dosyası alınamadı: %s", e)
        return _codes_cache


def validate_license(code: str, ip: str = None) -> dict:
    """Lisans kodunu doğrula. ip: aktivasyonu yapan sunucunun IP'si."""
    try:
        code = code.strip().upper()
        if not code.startswith("ankavm-"):
            return {"valid": False, "error": "Geçersiz lisans kodu formatı"}

        parts = code.split("-")
        if len(parts) != 5 or not all(len(p) == 4 for p in parts[1:]):
            return {"valid": False, "error": "Geçersiz lisans kodu formatı (ankavm-XXXX-XXXX-XXXX-XXXX)"}

        codes = _fetch_license_codes()
        if not codes:
            return {"valid": False, "error": "Lisans sunucusuna bağlanılamadı. Lütfen internet bağlantısını kontrol edin."}

        code_hash = hashlib.sha256(code.encode()).hexdigest()
        records = {}
        if os.path.exists(ACTIVATIONS_FILE):
            try:
                with open(ACTIVATIONS_FILE) as f:
                    records = json.load(f)
            except Exception:
                records = {}
        for entry in records.values():
            if entry.get("code_hash") == code_hash:
                if entry.get("activation_count", 0) >= 1 and entry.get("ip") != ip:
                    return {"valid": False, "error": "Bu lisans kodu başka bir sunucuda kullanımda. Her lisans yalnızca 1 sunucuda kullanılabilir."}
                break

        if code in codes:
            _save_license(code, ip=ip)
            _record_activation(code, ip=ip)
            return {"valid": True, "code": code, "message": "Lisans başarıyla doğrulandı", "max_servers": 1}
        else:
            return {"valid": False, "error": "Lisans kodu bulunamadı veya geçersiz"}
    except Exception as e:
        log.error("validate_license beklenmeyen hata: %s", e, exc_info=True)
        return {"valid": False, "error": "Doğrulama hatası"}


def _save_license(code: str, ip: str = None):
    """Lisans bilgisini yerel olarak kaydet."""
    try:
        os.makedirs(os.path.dirname(LICENSE_FILE), exist_ok=True)
        data = {
            "active": True,
            "code_hash":    hashlib.sha256(code.encode()).hexdigest(),
            "code_prefix":  code[:14],
            "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "activated_ip": ip or "unknown",
        }
        with open(LICENSE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        try:
            os.chmod(LICENSE_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        log.error("Lisans kaydetme hatası: %s", e)


def _record_activation(code: str, ip: str = None):
    """Aktivasyon geçmişine kayıt ekle (kod başına tek kayıt — günceller)."""
    try:
        os.makedirs(os.path.dirname(ACTIVATIONS_FILE), exist_ok=True)

        records = {}
        if os.path.exists(ACTIVATIONS_FILE):
            try:
                with open(ACTIVATIONS_FILE) as f:
                    records = json.load(f)
            except Exception:
                records = {}

        code_hash = hashlib.sha256(code.encode()).hexdigest()

        existing_key = None
        for k, v in records.items():
            if v.get("code_hash") == code_hash:
                existing_key = k
                break

        entry = {
            "code_hash":       code_hash,
            "code_prefix":     code[:14],
            "ip":              ip or "unknown",
            "first_activated": records.get(existing_key, {}).get("first_activated",
                               time.strftime("%Y-%m-%dT%H:%M:%S")),
            "last_activated":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            "activation_count": records.get(existing_key, {}).get("activation_count", 0) + 1,
        }

        key = existing_key or code_hash[:16]
        records[key] = entry

        with open(ACTIVATIONS_FILE, "w") as f:
            json.dump(records, f, indent=2)
        try:
            os.chmod(ACTIVATIONS_FILE, 0o600)
        except Exception:
            pass

    except Exception as e:
        log.error("Aktivasyon kaydı hatası: %s", e)


def get_license_status() -> dict:
    """Mevcut lisans durumunu döndür."""
    try:
        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            if data.get("active"):
                return {
                    "active":       True,
                    "code_prefix":  data.get("code_prefix", ""),
                    "activated_at": data.get("activated_at", ""),
                    "activated_ip": data.get("activated_ip", ""),
                }
    except Exception as e:
        log.warning("Lisans okuma hatası: %s", e)
    return {"active": False}


def get_activations() -> list:
    """Tüm aktivasyon kayıtlarını döndür (yönetici paneli için)."""
    try:
        if os.path.exists(ACTIVATIONS_FILE):
            with open(ACTIVATIONS_FILE) as f:
                records = json.load(f)
            return sorted(records.values(),
                          key=lambda x: x.get("last_activated", ""), reverse=True)
    except Exception as e:
        log.error("Aktivasyon listesi okuma hatası: %s", e)
    return []


def deactivate_license() -> dict:
    """Lisansı deaktive et."""
    try:
        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            data["active"] = False
            with open(LICENSE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}






