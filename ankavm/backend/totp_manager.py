"""
totp_manager.py - KullanÄ±cÄ± bazlÄ± TOTP (Time-based One-Time Password) 2FA yÃ¶netimi.
Veri: /var/lib/ankavm/totp_data.json
pyotp yÃ¼klÃ¼ deÄŸilse graceful fallback.
"""

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

try:
    import qrcode
    import io, base64
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

import json
import os
import time
import threading
import logging

log = logging.getLogger("ankavm.totp")

DATA_PATH = "/var/lib/ankavm/totp_data.json"
_ISSUER   = "ankavm Hypervisor"
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


# ---------------------------------------------------------------------------
# TOTP yÃ¶netimi
# ---------------------------------------------------------------------------

def setup_totp(username):
    """
    KullanÄ±cÄ± iÃ§in TOTP secret Ã¼retir (henÃ¼z etkin deÄŸil).
    Zaten bekleyen (enabled=False) bir secret varsa YENÄ°DEN KULLANIR â€”
    bÃ¶ylece QR iki kez tarandÄ±ÄŸÄ±nda geÃ§ersizleÅŸmez.
    DÃ¶ner: {"secret": str, "uri": str, "available": True}
    pyotp yoksa: {"available": False, "error": "pyotp not installed"}
    """
    if not PYOTP_AVAILABLE:
        log.warning("setup_totp: pyotp yok.")
        return {"available": False, "error": "pyotp not installed"}
    try:
        with _lock:
            data   = _load()
            entry  = data.get(username, {})
            # Bekleyen (onaylanmamÄ±ÅŸ) secret varsa yeniden kullan
            if entry.get("secret") and not entry.get("enabled", False):
                secret = entry["secret"]
                log.info("setup_totp: %s iÃ§in mevcut pending secret kullanÄ±lÄ±yor.", username)
            else:
                secret = pyotp.random_base32()
                data[username] = {
                    "secret":     secret,
                    "enabled":    False,
                    "created_at": time.time(),
                }
                _save(data)
                log.info("setup_totp: %s iÃ§in yeni secret oluÅŸturuldu.", username)

        totp = pyotp.TOTP(secret)
        uri  = totp.provisioning_uri(name=username, issuer_name=_ISSUER)

        log.info("setup_totp: %s iÃ§in yeni secret oluÅŸturuldu.", username)

        # QR kod PNG â†’ base64 data URI
        qr_image = None
        if QRCODE_AVAILABLE:
            try:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=6,
                    border=3,
                )
                qr.add_data(uri)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                qr_image = "data:image/png;base64," + base64.b64encode(buf.read()).decode()
            except Exception as qr_err:
                log.warning("QR kod oluÅŸturulamadÄ±: %s", qr_err)

        return {"secret": secret, "uri": uri, "available": True, "qr_image": qr_image}
    except Exception as e:
        log.error("setup_totp hatasÄ± (username=%s): %s", username, e)
        return {"available": False, "error": str(e)}


def verify_totp(username, code):
    """
    KullanÄ±cÄ±nÄ±n TOTP kodunu doÄŸrular.
    pyotp yoksa veya kullanÄ±cÄ± kayÄ±tlÄ± deÄŸilse False dÃ¶ndÃ¼rÃ¼r.
    window=1 â†’ Â±1 periyot (30 saniyelik) tolerans.
    """
    if not PYOTP_AVAILABLE:
        return False
    try:
        with _lock:
            data = _load()
        entry = data.get(username)
        if not entry or not entry.get("secret"):
            return False
        totp = pyotp.TOTP(entry["secret"])
        # valid_window=3 â†’ mevcut Â±3 periyot = Â±90 sn clock skew tolere eder
        return totp.verify(str(code).strip(), valid_window=3)
    except Exception as e:
        log.error("verify_totp hatasÄ± (username=%s): %s", username, e)
        return False


def enable_totp(username, code):
    """
    Kodu doÄŸrulayÄ±p TOTP'u etkinleÅŸtirir.
    DÃ¶ner: True (baÅŸarÄ±) / False (kod yanlÄ±ÅŸ veya hata)
    """
    if not PYOTP_AVAILABLE:
        log.warning("enable_totp: pyotp yok.")
        return False
    try:
        if not verify_totp(username, code):
            log.warning("enable_totp: geÃ§ersiz kod (username=%s).", username)
            return False
        with _lock:
            data = _load()
            if username not in data:
                log.warning("enable_totp: kullanÄ±cÄ± bulunamadÄ± (%s).", username)
                return False
            data[username]["enabled"] = True
            _save(data)
        log.info("enable_totp: %s iÃ§in TOTP etkinleÅŸtirildi.", username)
        return True
    except Exception as e:
        log.error("enable_totp hatasÄ± (username=%s): %s", username, e)
        return False


def disable_totp(username):
    """
    KullanÄ±cÄ±nÄ±n TOTP'unu devre dÄ±ÅŸÄ± bÄ±rakÄ±r.
    DÃ¶ner: True (baÅŸarÄ±) / False (hata veya kullanÄ±cÄ± bulunamadÄ±)
    """
    try:
        with _lock:
            data = _load()
            if username not in data:
                log.warning("disable_totp: kullanÄ±cÄ± bulunamadÄ± (%s).", username)
                return False
            data[username]["enabled"] = False
            _save(data)
        log.info("disable_totp: %s iÃ§in TOTP devre dÄ±ÅŸÄ±.", username)
        return True
    except Exception as e:
        log.error("disable_totp hatasÄ± (username=%s): %s", username, e)
        return False


def is_enabled(username):
    """KullanÄ±cÄ± iÃ§in TOTP etkin mi? bool dÃ¶ndÃ¼rÃ¼r."""
    try:
        with _lock:
            data = _load()
        entry = data.get(username)
        if not entry:
            return False
        return bool(entry.get("enabled", False))
    except Exception as e:
        log.error("is_enabled hatasÄ± (username=%s): %s", username, e)
        return False


def get_status(username):
    """
    KullanÄ±cÄ± TOTP durumunu dÃ¶ndÃ¼rÃ¼r.
    {"enabled": bool, "available": bool}
    """
    return {
        "enabled":   is_enabled(username),
        "available": PYOTP_AVAILABLE,
    }






