"""
ankavm GÃ¼venlik KatmanÄ±
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
1.  Rate limiting      â€” brute-force Ã¶nleme (login + genel API)
2.  Security headers   â€” HSTS, CSP, X-Frame-Options, vb.
3.  Input sanitization â€” VM adÄ±, dosya yollarÄ±, UUID doÄŸrulama
4.  Path traversal     â€” dosya yolu saldÄ±rÄ±larÄ±nÄ± Ã¶nle
5.  Request logging    â€” gÃ¼venlik denetim kaydÄ±
"""

import re
import os
import time
import threading
import ipaddress
import hashlib
import logging
from functools import wraps
from flask import request, jsonify, g

log = logging.getLogger("ankavm.security")

# â”€â”€ 1. Rate Limiter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class RateLimiter:
    # rapor #44 fix: OOM Ã¶nleme â€” maksimum bucket sayÄ±sÄ±
    _MAX_BUCKETS = 50_000

    def __init__(self):
        self._lock    = threading.Lock()
        self._buckets: dict = {}

    def _key(self, ip: str, endpoint: str) -> str:
        return f"{ip}:{endpoint}"

    def check(
        self,
        ip: str,
        endpoint: str,
        max_calls: int = 30,
        window_secs: int = 60,
    ) -> tuple:
        """
        DÃ¶ndÃ¼rÃ¼r: (allowed: bool, retry_after: int)
        """
        key = self._key(ip, endpoint)
        now = time.time()

        with self._lock:
            # rapor #44 fix: bucket cap â€” Ã§ok fazla unique IP â†’ en eskiyi at
            if len(self._buckets) >= self._MAX_BUCKETS and key not in self._buckets:
                # LRU benzeri: en eski blocked_until olan bucket'Ä± sil
                try:
                    oldest = min(self._buckets, key=lambda k: self._buckets[k]["blocked_until"])
                    del self._buckets[oldest]
                except Exception:
                    pass

            bucket = self._buckets.get(key, {"calls": [], "blocked_until": 0})

            if bucket["blocked_until"] > now:
                return False, int(bucket["blocked_until"] - now)

            # Pencere dÄ±ÅŸÄ±ndaki Ã§aÄŸrÄ±larÄ± temizle
            bucket["calls"] = [t for t in bucket["calls"] if now - t < window_secs]

            if len(bucket["calls"]) >= max_calls:
                block_until = now + window_secs
                bucket["blocked_until"] = block_until
                self._buckets[key] = bucket
                log.warning("Rate limit aÅŸÄ±ldÄ±: %s / %s", ip, endpoint)
                return False, window_secs

            bucket["calls"].append(now)
            self._buckets.setdefault(key, bucket)
            self._buckets[key] = bucket
            return True, 0

    def cleanup(self):
        """Eski kayÄ±tlarÄ± temizle (periyodik Ã§aÄŸrÄ±lmalÄ±)."""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._buckets.items()
                       if v["blocked_until"] < now and not v["calls"]]
            for k in expired:
                del self._buckets[k]


_limiter = RateLimiter()

# Endpoint bazlÄ± limitler
RATE_LIMITS = {
    "/api/auth/login":    (5,   60),   # 5 deneme / dakika (brute-force)
    "/api/setup/init":    (3,  300),   # 3 deneme / 5 dakika
    "/api/provision":     (10,  60),   # 10 kurulum / dakika
    # NOT: /api/storage/isos GET (liste) burada YOK â€” default 120/dk kullanÄ±r
    # POST/DELETE upload limiti endpoint handler'Ä±nda kontrol edilir
    "default":            (120, 60),   # Genel API: 120 istek / dakika
}


def rate_limit_middleware(app):
    """Flask before_request hook olarak ekle."""
    @app.before_request
    def check_rate_limit():
        if not request.path.startswith("/api/"):
            return

        ip = _get_real_ip()
        path = request.path

        max_calls, window = RATE_LIMITS.get(path, RATE_LIMITS["default"])
        allowed, retry_after = _limiter.check(ip, path, max_calls, window)

        if not allowed:
            log.warning("Rate limit: %s â†’ %s (retry: %ds)", ip, path, retry_after)
            resp = jsonify({
                "error": "Ã‡ok fazla istek. LÃ¼tfen bekleyin.",
                "retry_after": retry_after,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(retry_after)
            return resp


# â”€â”€ 2. Security Headers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def security_headers_middleware(app):
    @app.after_request
    def add_headers(response):
        # /console/ ve /novnc/ sayfalarÄ± iframe embed gerektiriyor â€” frame kÄ±sÄ±tlamasÄ± uygulanmaz
        path = request.path
        is_console_path = (path.startswith("/console/") or path.startswith("/novnc/")
                          or path.startswith("/vnc_console/"))

        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["X-Frame-Options"]           = "SAMEORIGIN" if is_console_path else "DENY"
        response.headers["X-XSS-Protection"]          = "1; mode=block"
        response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]        = "geolocation=(), camera=(), microphone=()"
        if not is_console_path:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"]        = "no-cache"

        # HSTS (yalnÄ±zca HTTPS'de)
        # NOT: preload kullanma â€” self-signed / yenilenen sertifikalarda
        # tarayÄ±cÄ± kalÄ±cÄ± olarak bloke olur ve "proceed anyway" seÃ§eneÄŸi Ã§Ä±kmaz.
        # max-age=300 (5 dakika) â†’ sertifika sorunlarÄ±nda hÄ±zlÄ± kurtarma saÄŸlar.
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = \
                "max-age=300"

        # CSP â€” console/novnc iÃ§in frame-ancestors 'self', diÄŸerleri iÃ§in 'none'
        frame_ancestors = "'self'" if is_console_path else "'none'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' wss: ws:; "
            f"frame-ancestors {frame_ancestors};"
        )
        return response


# â”€â”€ 3. Input Sanitization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# VM adÄ±: sadece alfanÃ¼merik, tire, alt Ã§izgi (3-64 karakter)
_VM_NAME_RE   = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
# UUID: standart format
_UUID_RE      = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
# Dosya adÄ±: yol traversal karakterleri yok
_SAFE_FNAME_RE = re.compile(r"^[a-zA-Z0-9_\-. ]{1,255}$")
# IP adresi
_IP_RE        = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def validate_vm_name(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("VM adÄ± boÅŸ olamaz")
    name = name.strip()
    if not _VM_NAME_RE.match(name):
        raise ValueError(
            "VM adÄ± yalnÄ±zca harf, rakam, tire ve alt Ã§izgi iÃ§erebilir (1-64 karakter)"
        )
    # Tehlikeli kalÄ±plar
    for bad in ["../", "//", "..", "\\", ";", "|", "&", "`", "$("]:
        if bad in name:
            raise ValueError(f"VM adÄ±nda geÃ§ersiz karakter: {bad!r}")
    return name


def validate_uuid(value: str, field: str = "id") -> str:
    if not value or not isinstance(value, str):
        raise ValueError(f"{field} boÅŸ olamaz")
    if not _UUID_RE.match(value.strip()):
        raise ValueError(f"GeÃ§ersiz UUID formatÄ±: {field}")
    return value.strip().lower()


def validate_filename(name: str) -> str:
    if not name or not isinstance(name, str):
        raise ValueError("Dosya adÄ± boÅŸ olamaz")
    name = os.path.basename(name)  # yol bileÅŸenlerini kaldÄ±r
    if not _SAFE_FNAME_RE.match(name):
        raise ValueError("GeÃ§ersiz dosya adÄ± karakterleri")
    if name.startswith(".") or name.startswith("-"):
        raise ValueError("Dosya adÄ± nokta veya tire ile baÅŸlayamaz")
    return name


def validate_path_safe(path: str, allowed_roots: list[str]) -> str:
    """Path traversal saldÄ±rÄ±sÄ±nÄ± Ã¶nle."""
    path = os.path.realpath(os.path.abspath(path))
    for root in allowed_roots:
        root = os.path.realpath(os.path.abspath(root))
        if path.startswith(root + os.sep) or path == root:
            return path
    raise ValueError(f"GÃ¼vensiz dosya yolu. Ä°zin verilen kÃ¶kler: {allowed_roots}")


def validate_ip(ip: str) -> str:
    if not ip:
        raise ValueError("IP adresi boÅŸ olamaz")
    try:
        return str(ipaddress.IPv4Address(ip.strip()))
    except Exception:
        raise ValueError(f"GeÃ§ersiz IP adresi: {ip!r}")


def validate_network_cidr(cidr: str) -> str:
    try:
        return str(ipaddress.IPv4Network(cidr.strip(), strict=False))
    except Exception:
        raise ValueError(f"GeÃ§ersiz CIDR: {cidr!r}")


def validate_port(port, low: int = 1, high: int = 65535) -> int:
    try:
        p = int(port)
        if not (low <= p <= high):
            raise ValueError
        return p
    except (ValueError, TypeError):
        raise ValueError(f"GeÃ§ersiz port: {port!r} ({low}-{high} aralÄ±ÄŸÄ±nda olmalÄ±)")


def sanitize_str(value: str, max_len: int = 256) -> str:
    """Temel string temizliÄŸi."""
    if not isinstance(value, str):
        raise ValueError("Beklenen string deÄŸer")
    value = value.strip()[:max_len]
    # Null byte
    value = value.replace("\x00", "")
    return value


def validate_memory_mb(value) -> int:
    v = int(value)
    if not (64 <= v <= 1_048_576):   # 64 MB â€“ 1 TB
        raise ValueError(f"GeÃ§ersiz bellek deÄŸeri: {v} MB (64 MBâ€“1 TB)")
    return v


def validate_disk_gb(value) -> int:
    v = int(value)
    if not (1 <= v <= 65536):   # 1 GB â€“ 64 TB
        raise ValueError(f"GeÃ§ersiz disk boyutu: {v} GB (1 GBâ€“64 TB)")
    return v


def validate_vcpus(value) -> int:
    v = int(value)
    if not (1 <= v <= 512):
        raise ValueError(f"GeÃ§ersiz vCPU sayÄ±sÄ±: {v} (1-512)")
    return v


# â”€â”€ 4. Denetim kaydÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def audit_log_middleware(app):
    @app.before_request
    def before():
        g.request_start = time.time()

    @app.after_request
    def after(response):
        if not request.path.startswith("/api/"):
            return response
        duration = round((time.time() - getattr(g, "request_start", time.time())) * 1000, 1)
        ip = _get_real_ip()
        # Sadece deÄŸiÅŸtirici iÅŸlemleri kaydet
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            log.info(
                "%s %s %s %dms â€” %s",
                request.method, request.path, response.status_code, duration, ip,
            )
        return response


# â”€â”€ 5. Error Handler â€” Stack trace sÄ±zdÄ±rma â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def safe_error_handlers(app):
    @app.errorhandler(Exception)
    def handle_exception(e):
        log.error("Beklenmeyen hata: %s", e, exc_info=True)
        # Ä°stemciye stack trace gÃ¶sterme
        return jsonify({"error": "Sunucu hatasÄ±. LÃ¼tfen yÃ¶neticiye baÅŸvurun."}), 500

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "GeÃ§ersiz istek"}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Kimlik doÄŸrulama gerekli"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "EriÅŸim reddedildi"}), 403

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Kaynak bulunamadÄ±"}), 404
        from flask import render_template
        return render_template("index.html")

    @app.errorhandler(429)
    def too_many(e):
        return jsonify({"error": "Ã‡ok fazla istek"}), 429


# â”€â”€ YardÄ±mcÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_real_ip() -> str:
    """Proxy arkasÄ±ndan gerÃ§ek IP al (gÃ¼venli).
    OXW-2026-004 fix: XFF baÅŸlÄ±ÄŸÄ±na yalnÄ±zca config.TRUSTED_PROXIES CIDR'inden
    gelen isteklerde gÃ¼venilir. DiÄŸer kaynaklardan gelen XFF baÅŸlÄ±klarÄ± IP spoofing
    iÃ§in kullanÄ±labilir ve rate-limit/lockout bypass'a yol aÃ§ar.
    """
    import config as _cfg
    remote = request.remote_addr or ""
    try:
        remote_addr = ipaddress.ip_address(remote)
        _trusted_nets = [ipaddress.ip_network(c, strict=False)
                         for c in _cfg.TRUSTED_PROXIES]
        if any(remote_addr in net for net in _trusted_nets):
            xff = request.headers.get("X-Forwarded-For", "")
            if xff:
                # En sondaki IP'yi al: client, proxy1, proxy2, ..., trusted-proxy â†’ biz
                return xff.split(",")[-1].strip()
    except Exception:
        pass
    return remote


def register_security(app):
    """TÃ¼m gÃ¼venlik middleware'lerini uygulamaya kaydet."""
    rate_limit_middleware(app)
    security_headers_middleware(app)
    audit_log_middleware(app)
    safe_error_handlers(app)
    log.info("GÃ¼venlik katmanÄ± aktif")






