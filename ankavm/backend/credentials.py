"""
ankavm Åifreli Kimlik Bilgisi Sistemi
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Dosya konumlarÄ±:
  /etc/ankavm/.auth            â€” Åifreli kimlik bilgileri (AES-256-CBC)
  /etc/ankavm/.passwd_reset    â€” Åifre sÄ±fÄ±rlama dosyasÄ± (varsa uygula, sonra sil)

Åifre deÄŸiÅŸtirme:
  AÅŸaÄŸÄ±daki formatta /etc/ankavm/.passwd_reset dosyasÄ± oluÅŸturun:
    USERNAME=yeni_kullanici
    PASSWORD=yeni_sifre
  Servis yeniden baÅŸladÄ±ÄŸÄ±nda otomatik uygular ve dosyayÄ± siler.

Encryption key: Makine UUID'sinden tÃ¼retilir (her sunucuya Ã¶zgÃ¼).
"""

import os
import json
import hashlib
import secrets
import time
from pathlib import Path

AUTH_FILE        = os.environ.get("ankavm_AUTH_FILE",  os.environ.get("ADAOS_AUTH_FILE",  "/etc/ankavm/.auth"))
RESET_FILE       = os.environ.get("ankavm_RESET_FILE", os.environ.get("ADAOS_RESET_FILE", "/etc/ankavm/.passwd_reset"))
SETUP_FLAG_FILE  = "/etc/ankavm/.setup_done"
# Username plaintext yedek dosyasÄ± â€” machine-id deÄŸiÅŸse bile username okunabilir kalÄ±r
USERNAME_FILE    = "/etc/ankavm/.username"

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    _CRYPTO = True
except ImportError:
    _CRYPTO = False


_FALLBACK_KEY_FILE = "/etc/ankavm/.machine_fallback_key"


def _machine_key() -> bytes:
    """Makineye Ã¶zgÃ¼ ÅŸifreleme anahtarÄ± Ã¼retir."""
    seeds = []
    for f in ["/etc/machine-id", "/var/lib/dbus/machine-id", "/sys/class/dmi/id/product_uuid"]:
        try:
            seeds.append(Path(f).read_text().strip())
        except Exception:
            pass
    if not seeds:
        # machine-id yoksa: cihaza Ã¶zel rastgele anahtar Ã¼ret ve sakla
        try:
            if os.path.exists(_FALLBACK_KEY_FILE):
                seeds.append(Path(_FALLBACK_KEY_FILE).read_text().strip())
            else:
                fallback = secrets.token_hex(32)
                os.makedirs(os.path.dirname(_FALLBACK_KEY_FILE), exist_ok=True)
                Path(_FALLBACK_KEY_FILE).write_text(fallback)
                os.chmod(_FALLBACK_KEY_FILE, 0o600)
                seeds.append(fallback)
        except Exception:
            seeds.append(secrets.token_hex(32))
    combined = "|".join(seeds) + "|ankavm-v1"
    return hashlib.sha256(combined.encode()).digest()


def _xor_cipher(data: bytes, key: bytes) -> bytes:
    """Kriptografi kÃ¼tÃ¼phanesi yoksa XOR ÅŸifreleme."""
    key_bytes = (key * (len(data) // len(key) + 1))[:len(data)]
    return bytes(a ^ b for a, b in zip(data, key_bytes))


def _encrypt(plaintext: str) -> str:
    key = _machine_key()
    data = plaintext.encode("utf-8")

    if _CRYPTO:
        iv = secrets.token_bytes(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        enc = cipher.encryptor()
        ct = enc.update(padded) + enc.finalize()
        return (iv + ct).hex()
    else:
        iv = secrets.token_bytes(16)
        return (iv + _xor_cipher(data, key)).hex()


def _decrypt(hex_data: str) -> str:
    key = _machine_key()
    raw = bytes.fromhex(hex_data)
    iv, ct = raw[:16], raw[16:]

    if _CRYPTO:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        padded = dec.update(ct) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
    else:
        return _xor_cipher(ct, key).decode("utf-8")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        new_h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return secrets.compare_digest(h, new_h.hex())
    except Exception:
        return False


def _load_auth() -> dict:
    if not os.path.exists(AUTH_FILE):
        return {}
    try:
        raw = Path(AUTH_FILE).read_text().strip()
        return json.loads(_decrypt(raw))
    except Exception:
        return {}


def _save_auth(data: dict):
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    encrypted = _encrypt(json.dumps(data))
    Path(AUTH_FILE).write_text(encrypted)
    os.chmod(AUTH_FILE, 0o600)
    # Username ayrÄ±ca plaintext kaydedilir â€” machine-id deÄŸiÅŸse bile okunabilir
    try:
        if data.get("username"):
            Path(USERNAME_FILE).write_text(data["username"])
            os.chmod(USERNAME_FILE, 0o600)
    except Exception:
        pass


def is_setup_done() -> bool:
    # Auth dosyasÄ± veya username yedeÄŸi varsa setup tamamlanmÄ±ÅŸ sayÄ±lÄ±r.
    # machine-id deÄŸiÅŸmiÅŸ olsa bile setup sayfasÄ± AÃ‡ILMAZ.
    if os.path.exists(SETUP_FLAG_FILE) and os.path.exists(AUTH_FILE):
        return True
    # Yedek: username dosyasÄ± varsa setup yapÄ±lmÄ±ÅŸ ama auth silinmiÅŸ/bozulmuÅŸ olabilir
    if os.path.exists(USERNAME_FILE) and os.path.exists(AUTH_FILE):
        return True
    return False


def first_setup(username: str, password: str):
    """Ä°lk kurulum sÄ±rasÄ±nda kimlik bilgilerini ayarla."""
    if is_setup_done():
        raise RuntimeError("Kurulum zaten tamamlanmÄ±ÅŸ. Åifre deÄŸiÅŸtirmek iÃ§in .passwd_reset kullanÄ±n.")

    data = {
        "username": username,
        "password_hash": _hash_password(password),
        "created_at": time.time(),
        "last_changed": time.time(),
    }
    _save_auth(data)

    os.makedirs(os.path.dirname(SETUP_FLAG_FILE), exist_ok=True)
    Path(SETUP_FLAG_FILE).write_text(f"setup_completed={time.time()}\n")
    os.chmod(SETUP_FLAG_FILE, 0o600)


def verify_credentials(username: str, password: str) -> bool:
    data = _load_auth()
    if not data:
        # Auth dosyasÄ± Ã§Ã¶zÃ¼lemedi (machine-id deÄŸiÅŸmiÅŸ olabilir)
        import logging as _log
        _log.getLogger("ankavm.credentials").critical(
            "GÄ°RÄ°Å BAÅARISIZ: .auth dosyasÄ± Ã§Ã¶zÃ¼lemedi. "
            "machine-id deÄŸiÅŸmiÅŸ olabilir. "
            "Åifreyi sÄ±fÄ±rlamak iÃ§in root olarak: "
            "printf 'USERNAME=%s\\nPASSWORD=yeni_sifre\\n' > /etc/ankavm/.passwd_reset && "
            "chmod 600 /etc/ankavm/.passwd_reset && systemctl restart ankavm",
            username
        )
        return False
    if data.get("username", "").lower() != username.lower():
        return False
    return _verify_password(password, data.get("password_hash", ""))


def get_username() -> str:
    # Ã–nce ÅŸifreli auth dosyasÄ±ndan dene
    # NOTE: login her zaman .lower() uygular (api_login satÄ±r ~889), bu yÃ¼zden
    # burada da normalize ediyoruz â€” JWT identity her zaman lowercase olduÄŸu iÃ§in
    # username == get_username() karÅŸÄ±laÅŸtÄ±rmalarÄ± case-mismatch yÃ¼zÃ¼nden "viewer"
    # dÃ¶nmesin diye. (OXW-RBAC-001 fix)
    data = _load_auth()
    if data.get("username"):
        return data["username"].strip().lower()
    # Åifreli dosya Ã§Ã¶zÃ¼lemediyse (machine-id deÄŸiÅŸmiÅŸ olabilir) plaintext yedeÄŸe bak
    try:
        if os.path.exists(USERNAME_FILE):
            uname = Path(USERNAME_FILE).read_text().strip().lower()
            if uname:
                import logging as _log
                _log.getLogger("ankavm.credentials").critical(
                    "AUTH DOSYASI Ã‡Ã–ZÃœLEMEDI! machine-id deÄŸiÅŸmiÅŸ olabilir. "
                    "USERNAME_FILE yedeÄŸinden '%s' okundu. "
                    "Åifreyi sÄ±fÄ±rlamak iÃ§in: /etc/ankavm/.passwd_reset dosyasÄ± oluÅŸturun.",
                    uname
                )
                return uname
    except Exception:
        pass
    return "admin"


def apply_reset_if_exists():
    """
    /etc/ankavm/.passwd_reset dosyasÄ± varsa ÅŸifreyi gÃ¼nceller ve dosyayÄ± siler.
    Servis baÅŸlangÄ±cÄ±nda Ã§aÄŸrÄ±lmalÄ±dÄ±r.

    Dosya formatÄ±:
        USERNAME=yeni_kullanici_adi
        PASSWORD=yeni_sifre
    """
    if not os.path.exists(RESET_FILE):
        return False

    try:
        import stat as _stat
        _st = os.stat(RESET_FILE)

        # Dosya root (uid=0) tarafÄ±ndan oluÅŸturulmuÅŸ olmalÄ±
        if _st.st_uid != 0:
            print(f"[credentials] RESET_FILE root'a ait deÄŸil (uid={_st.st_uid}) â€” reddedildi: {RESET_FILE}")
            try:
                os.remove(RESET_FILE)
            except OSError:
                pass
            return False

        # GÃ¼venlik: dosya group/world-readable ise reddet
        if _st.st_mode & (_stat.S_IRWXG | _stat.S_IRWXO):
            print(f"[credentials] RESET_FILE group/world-readable â€” gÃ¼venlik riski, reddedildi: {RESET_FILE}")
            try:
                os.remove(RESET_FILE)
            except OSError:
                pass
            return False
    except OSError:
        return False

    try:
        content = Path(RESET_FILE).read_text().strip()
        params = {}
        for line in content.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                params[k.strip().upper()] = v.strip()

        new_user = params.get("USERNAME", "").strip()
        new_pass = params.get("PASSWORD", "").strip()

        if not new_user or not new_pass:
            raise ValueError("USERNAME veya PASSWORD eksik")

        data = _load_auth()
        data["username"] = new_user
        data["password_hash"] = _hash_password(new_pass)
        data["last_changed"] = time.time()
        _save_auth(data)

        # DosyayÄ± gÃ¼venli ÅŸekilde sil
        os.remove(RESET_FILE)
        print(f"[credentials] Åifre sÄ±fÄ±rlama uygulandÄ±. KullanÄ±cÄ±: {new_user}")
        return True

    except Exception as e:
        print(f"[credentials] SÄ±fÄ±rlama dosyasÄ± iÅŸlenemedi: {e}")
        # GÃ¼venlik iÃ§in yine de sil
        try:
            os.remove(RESET_FILE)
        except Exception:
            pass
        return False


def change_password(old_password: str, new_password: str) -> bool:
    """Mevcut ÅŸifre doÄŸrulanarak yeni ÅŸifre ayarla."""
    data = _load_auth()
    if not _verify_password(old_password, data.get("password_hash", "")):
        return False
    data["password_hash"] = _hash_password(new_password)
    data["last_changed"] = time.time()
    _save_auth(data)
    return True


def get_credential_info() -> dict:
    """Åifre bilgilerini dÃ¶ndÃ¼r (hash olmadan)."""
    data = _load_auth()
    return {
        "username": data.get("username", "â€”"),
        "created_at": data.get("created_at"),
        "last_changed": data.get("last_changed"),
        "setup_done": is_setup_done(),
    }







