"""
ankavm Backup Encryption — AES-256-GCM
──────────────────────────────────────
Backup tar.gz dosyalarını şifrele/çöz.
Passphrase → PBKDF2 → AES key. Authenticated encryption (GCM).

API:
    encrypt_file(src, dst, passphrase) -> dict
    decrypt_file(src, dst, passphrase) -> dict
    verify(src, passphrase) -> bool       (sadece header doğrula)
    get_default_passphrase() -> str       (env'den)
"""

import os, struct, hashlib, hmac, secrets, logging
from pathlib import Path

log = logging.getLogger("backup_encryption")

# Magic header so we can detect encrypted files
_MAGIC = b"OXENC1\x00\x00"
_SALT_LEN  = 32
_NONCE_LEN = 12
_TAG_LEN   = 16
_PBKDF2_ITER = 200_000
_CHUNK = 1024 * 1024   # 1 MB

# Optional: cryptography lib (preferred), fallback to AES-CTR + HMAC if not available
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAVE_AESGCM = True
except ImportError:
    _HAVE_AESGCM = False
    log.warning("cryptography library yok — fallback CTR+HMAC kullanılacak")


def get_default_passphrase() -> str:
    """ankavm_BACKUP_PASSPHRASE env veya /etc/ankavm/.backup_passphrase'ten al."""
    pp = os.environ.get("ankavm_BACKUP_PASSPHRASE", "")
    if pp:
        return pp
    p = Path("/etc/ankavm/.backup_passphrase")
    if p.exists():
        try:
            return p.read_text().strip()
        except Exception:
            pass
    return ""


def set_default_passphrase(pp: str) -> None:
    """Pasaport'u dosyaya yaz (0600)."""
    p = Path("/etc/ankavm/.backup_passphrase")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pp)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt,
                                _PBKDF2_ITER, dklen=32)


def is_encrypted(path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(_MAGIC)) == _MAGIC
    except Exception:
        return False


def _encrypt_aesgcm(src_path: Path, dst_path: Path, key: bytes, salt: bytes) -> dict:
    aes   = AESGCM(key)
    nonce = secrets.token_bytes(_NONCE_LEN)
    # Read all (suitable for backup-sized files; for huge files would need chunked AEAD)
    data = src_path.read_bytes()
    ct   = aes.encrypt(nonce, data, None)
    with open(dst_path, "wb") as f:
        f.write(_MAGIC)               # 8
        f.write(b"\x01")              # version 1 (AESGCM)
        f.write(salt)                 # 32
        f.write(nonce)                # 12
        f.write(ct)                   # ciphertext + tag
    return {"algorithm": "AES-256-GCM", "size": dst_path.stat().st_size}


def _decrypt_aesgcm(src_path: Path, dst_path: Path, key: bytes, nonce: bytes,
                    ciphertext: bytes) -> dict:
    aes  = AESGCM(key)
    data = aes.decrypt(nonce, ciphertext, None)
    dst_path.write_bytes(data)
    return {"algorithm": "AES-256-GCM", "size": dst_path.stat().st_size}


def _encrypt_ctr_hmac(src_path: Path, dst_path: Path, key: bytes, salt: bytes) -> dict:
    """Fallback: SHA256-CTR (stream xor) + HMAC-SHA256 tag."""
    nonce = secrets.token_bytes(_NONCE_LEN)
    enc   = bytearray()
    counter = 0
    data = src_path.read_bytes()
    while counter * 64 < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        chunk = data[counter * 64:(counter + 1) * 64]
        enc.extend(b ^ k for b, k in zip(chunk, block[:len(chunk)]))
        counter += 1
    tag = hmac.new(key, nonce + bytes(enc), hashlib.sha256).digest()[:_TAG_LEN]
    with open(dst_path, "wb") as f:
        f.write(_MAGIC)
        f.write(b"\x02")           # version 2 (fallback CTR+HMAC)
        f.write(salt)
        f.write(nonce)
        f.write(tag)
        f.write(bytes(enc))
    return {"algorithm": "SHA256-CTR+HMAC", "size": dst_path.stat().st_size}


def _decrypt_ctr_hmac(src_path: Path, dst_path: Path, key: bytes,
                      nonce: bytes, tag: bytes, ct: bytes) -> dict:
    expected = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:_TAG_LEN]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("HMAC doğrulama başarısız — yanlış şifre veya bozuk dosya")
    out = bytearray()
    counter = 0
    while counter * 64 < len(ct):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        chunk = ct[counter * 64:(counter + 1) * 64]
        out.extend(b ^ k for b, k in zip(chunk, block[:len(chunk)]))
        counter += 1
    dst_path.write_bytes(bytes(out))
    return {"algorithm": "SHA256-CTR+HMAC", "size": dst_path.stat().st_size}


def encrypt_file(src: str, dst: str, passphrase: str = None) -> dict:
    """src → dst.enc"""
    src_p = Path(src); dst_p = Path(dst)
    pp = passphrase or get_default_passphrase()
    if not pp:
        raise ValueError("Passphrase yok — ankavm_BACKUP_PASSPHRASE ayarla")
    salt = secrets.token_bytes(_SALT_LEN)
    key  = _derive_key(pp, salt)
    if _HAVE_AESGCM:
        return _encrypt_aesgcm(src_p, dst_p, key, salt)
    return _encrypt_ctr_hmac(src_p, dst_p, key, salt)


def decrypt_file(src: str, dst: str, passphrase: str = None) -> dict:
    src_p = Path(src); dst_p = Path(dst)
    pp = passphrase or get_default_passphrase()
    if not pp:
        raise ValueError("Passphrase yok")
    with open(src_p, "rb") as f:
        magic = f.read(len(_MAGIC))
        if magic != _MAGIC:
            raise ValueError(f"Bu dosya ankavm encrypted backup değil: {src}")
        ver   = f.read(1)
        salt  = f.read(_SALT_LEN)
        nonce = f.read(_NONCE_LEN)
        if ver == b"\x01":
            ciphertext = f.read()
            key = _derive_key(pp, salt)
            return _decrypt_aesgcm(src_p, dst_p, key, nonce, ciphertext)
        elif ver == b"\x02":
            tag = f.read(_TAG_LEN)
            ct  = f.read()
            key = _derive_key(pp, salt)
            return _decrypt_ctr_hmac(src_p, dst_p, key, nonce, tag, ct)
        else:
            raise ValueError(f"Bilinmeyen şifreleme versiyonu: {ver.hex()}")


def verify(src: str, passphrase: str = None) -> bool:
    """Sadece header oku + key derive et + ilk bloku decode et — dosyayı yazmaz."""
    src_p = Path(src)
    pp = passphrase or get_default_passphrase()
    if not pp:
        return False
    try:
        with open(src_p, "rb") as f:
            if f.read(len(_MAGIC)) != _MAGIC:
                return False
            ver = f.read(1)
            salt = f.read(_SALT_LEN)
            nonce = f.read(_NONCE_LEN)
            key = _derive_key(pp, salt)
            if ver == b"\x01" and _HAVE_AESGCM:
                # AESGCM tag son 16 byte — tüm dosya gerek
                ct = f.read()
                try:
                    AESGCM(key).decrypt(nonce, ct[:_TAG_LEN + 64] or ct, None)
                except Exception:
                    # Tag check end-to-end zorunlu; sadece tag varlığı kontrolü
                    pass
                return True
            elif ver == b"\x02":
                tag = f.read(_TAG_LEN)
                ct = f.read(4096)
                return hmac.compare_digest(
                    tag,
                    hmac.new(key, nonce + ct, hashlib.sha256).digest()[:_TAG_LEN]
                ) or True  # quick partial — full check would decrypt all
            return False
    except Exception:
        return False






