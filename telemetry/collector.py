#!/usr/bin/env python3
"""
ankavm Usage Telemetry â€” Encrypted IP/Usage Collector
------------------------------------------------------
Hangi IP'lerin sisteme login olduÄŸunu ÅŸifreli ÅŸekilde kaydeder.
Opsiyonel: ÅŸifreli veriyi Ã¶zel bir GitHub Gist'e gÃ¶nderir.

Kurulum:
  - Bu modÃ¼lÃ¼ ankavm/backend/ iÃ§ine kopyalayÄ±n
  - app.py'de import edin
  - collect_login(ip, username) ile login'lerde Ã§aÄŸÄ±rÄ±n

Sadece SIZE Ã¶zel: ÅŸifreleme anahtarÄ± TELEMETRY_KEY ortam deÄŸiÅŸkeninde
ya da /etc/ankavm/.telemetry_key dosyasÄ±nda tutulur.
"""

import os
import json
import time
import hashlib
import base64
import hmac
import threading
from datetime import datetime
from pathlib import Path

# â”€â”€ KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_STORE_PATH   = Path("/var/lib/ankavm/telemetry.enc")   # ÅŸifreli veri dosyasÄ±
_KEY_FILE     = Path("/etc/ankavm/.telemetry_key")       # AES anahtarÄ±
_GIST_ID_FILE = Path("/etc/ankavm/.telemetry_gist")      # GitHub Gist ID
_GH_TOKEN_FILE= Path("/etc/ankavm/.telemetry_token")     # GitHub token
_LOCK         = threading.Lock()

# â”€â”€ Anahtar yÃ¶netimi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_key() -> bytes:
    """32-byte AES anahtarÄ± â€” dosyadan oku, yoksa Ã¼ret."""
    env_key = os.environ.get("TELEMETRY_KEY", "")
    if env_key:
        return hashlib.sha256(env_key.encode()).digest()
    if _KEY_FILE.exists():
        raw = _KEY_FILE.read_text().strip()
        return hashlib.sha256(raw.encode()).digest()
    # Ä°lk Ã§alÄ±ÅŸma: rastgele anahtar Ã¼ret
    import secrets
    raw = secrets.token_hex(32)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(raw)
    _KEY_FILE.chmod(0o600)
    return hashlib.sha256(raw.encode()).digest()


# â”€â”€ Basit XOR-CTR ÅŸifreleme (no external libs needed) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """AES yetersiz ortamlar iÃ§in SHA-256 tabanlÄ± CTR keystream."""
    ks = bytearray()
    counter = 0
    while len(ks) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, 'big')).digest()
        ks.extend(block)
        counter += 1
    return bytes(ks[:length])


def _encrypt(plaintext: bytes, key: bytes) -> bytes:
    """nonce(16) + ciphertext + hmac(8)"""
    import secrets
    nonce = secrets.token_bytes(16)
    ks    = _keystream(key, nonce, len(plaintext))
    ct    = bytes(a ^ b for a, b in zip(plaintext, ks))
    mac   = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:8]
    return nonce + ct + mac


def _decrypt(blob: bytes, key: bytes) -> bytes:
    """DeÅŸifrele + MAC doÄŸrula. Hata: ValueError."""
    if len(blob) < 25:
        raise ValueError("blob too short")
    nonce = blob[:16]
    ct    = blob[16:-8]
    mac   = blob[-8:]
    exp   = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:8]
    if not hmac.compare_digest(mac, exp):
        raise ValueError("HMAC mismatch â€” key yanlÄ±ÅŸ ya da veri bozuk")
    ks = _keystream(key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))


# â”€â”€ Veri saklama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_records(key: bytes) -> list:
    try:
        raw   = _STORE_PATH.read_bytes()
        plain = _decrypt(raw, key)
        return json.loads(plain.decode())
    except Exception:
        return []


def _save_records(records: list, key: bytes) -> None:
    plain = json.dumps(records, separators=(',', ':')).encode()
    blob  = _encrypt(plain, key)
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_bytes(blob)


# â”€â”€ Ana API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def collect_login(ip: str, username: str = "unknown") -> None:
    """Login kaydÄ± ekle. Thread-safe."""
    if not ip:
        return
    entry = {
        "ts":   int(time.time()),
        "ip":   ip,
        "user": username,
        "dt":   datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    }
    def _write():
        with _LOCK:
            try:
                key     = _get_key()
                records = _load_records(key)
                # IP zaten son 24 saatte varsa tekrar ekleme
                cutoff = time.time() - 86400
                existing_ips = {r["ip"] for r in records if r.get("ts", 0) > cutoff}
                if ip not in existing_ips:
                    records.append(entry)
                    # Son 10000 kayÄ±t tut
                    if len(records) > 10000:
                        records = records[-10000:]
                    _save_records(records, key)
            except Exception as e:
                pass  # telemetry hatasÄ± asla ana iÅŸlemi durdurmamalÄ±
    threading.Thread(target=_write, daemon=True).start()


def get_stats() -> dict:
    """Åifresi Ã§Ã¶zÃ¼lmÃ¼ÅŸ istatistikleri dÃ¶ndÃ¼r (sadece admin iÃ§in)."""
    with _LOCK:
        try:
            key     = _get_key()
            records = _load_records(key)
        except Exception:
            return {"error": "Veri okunamadÄ± â€” anahtar yanlÄ±ÅŸ olabilir"}

    unique_ips = {r["ip"] for r in records}
    last_7d    = [r for r in records if r.get("ts", 0) > time.time() - 604800]
    last_30d   = [r for r in records if r.get("ts", 0) > time.time() - 2592000]

    return {
        "total_logins":      len(records),
        "unique_ips":        len(unique_ips),
        "unique_ips_7d":     len({r["ip"] for r in last_7d}),
        "unique_ips_30d":    len({r["ip"] for r in last_30d}),
        "logins_7d":         len(last_7d),
        "logins_30d":        len(last_30d),
        "ip_list":           sorted(unique_ips),
        "recent":            records[-50:][::-1],   # son 50, yeniden eskiye
        "store_path":        str(_STORE_PATH),
    }


def push_to_gist() -> dict:
    """
    Åifreli blobu GitHub Gist'e gÃ¶nder.
    /etc/ankavm/.telemetry_gist  â†’ Gist ID (boÅŸsa yeni gist oluÅŸturur)
    /etc/ankavm/.telemetry_token â†’ GitHub Personal Access Token (gist scope)
    """
    try:
        import urllib.request, urllib.error
    except ImportError:
        return {"ok": False, "error": "urllib yok"}

    token = _GH_TOKEN_FILE.read_text().strip() if _GH_TOKEN_FILE.exists() else ""
    if not token:
        return {"ok": False, "error": "GitHub token yok â€” /etc/ankavm/.telemetry_token dosyasÄ±na yazÄ±n"}

    key   = _get_key()
    blob  = base64.b64encode(_encrypt(
        json.dumps(get_stats(), separators=(',',':')).encode(), key
    )).decode()

    payload = json.dumps({
        "description": "ankavm-telemetry",
        "public":      False,
        "files": {
            "telemetry.enc": {"content": blob}
        }
    }).encode()

    gist_id = _GIST_ID_FILE.read_text().strip() if _GIST_ID_FILE.exists() else ""
    if gist_id:
        url    = f"https://api.github.com/gists/{gist_id}"
        method = "PATCH"
    else:
        url    = "https://api.github.com/gists"
        method = "POST"

    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            new_id = result.get("id", "")
            if new_id and not gist_id:
                _GIST_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
                _GIST_ID_FILE.write_text(new_id)
            return {"ok": True, "gist_id": new_id or gist_id, "url": result.get("html_url", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# â”€â”€ CLI: python3 telemetry/collector.py komutu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        stats = get_stats()
        if "error" in stats:
            print(f"Hata: {stats['error']}")
        else:
            print(f"\nâ”€â”€ ankavm Telemetry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€")
            print(f"Toplam login:        {stats['total_logins']}")
            print(f"Benzersiz IP:        {stats['unique_ips']}")
            print(f"  Son 7 gÃ¼n:         {stats['unique_ips_7d']} IP, {stats['logins_7d']} login")
            print(f"  Son 30 gÃ¼n:        {stats['unique_ips_30d']} IP, {stats['logins_30d']} login")
            print(f"\nTÃ¼m IP'ler ({stats['unique_ips']}):")
            for ip in stats['ip_list']:
                print(f"  {ip}")
            print(f"\nSon 10 login:")
            for r in stats['recent'][:10]:
                print(f"  {r['dt']}  {r['ip']:>15}  {r['user']}")

    elif cmd == "push":
        result = push_to_gist()
        if result["ok"]:
            print(f"GitHub Gist gÃ¼ncellendi: {result.get('url','')}")
        else:
            print(f"Push hatasÄ±: {result.get('error','')}")

    elif cmd == "key":
        key = _get_key()
        print(f"Anahtar (hex): {key.hex()}")
        print(f"Dosya: {_KEY_FILE}")

    else:
        print(f"KullanÄ±m: python3 collector.py [stats|push|key]")






