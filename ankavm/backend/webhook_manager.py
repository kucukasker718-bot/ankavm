"""
webhook_manager.py â€” Webhook management with HMAC signing and delivery logging
ankavm Hypervisor backend module
"""

import json
import hmac
import hashlib
import ipaddress
import logging
import os
import socket
import threading
import uuid
import time
from urllib.parse import urlparse

log = logging.getLogger("ankavm.webhooks")

WEBHOOKS_FILE = "/var/lib/ankavm/webhooks.json"
DELIVERY_LOG  = "/var/log/ankavm/webhook_deliveries.jsonl"

_lock          = threading.Lock()
_delivery_lock = threading.Lock()

SUPPORTED_EVENTS = [
    "vm.created", "vm.deleted", "vm.started", "vm.stopped", "vm.error",
    "snapshot.created", "snapshot.deleted", "backup.completed", "backup.failed",
    "alert.triggered", "network.changed", "user.login", "user.failed_login",
]

# Optional requests import with urllib fallback
try:
    import requests as _req
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    import urllib.request
    import urllib.error
    log.debug("requests not available â€” using urllib.request as fallback")

# OXW-2026-017 fix: Webhook SSRF block-list
# Ä°Ã§ aÄŸ / loopback / link-local adreslerine webhook gÃ¶nderilmez
_WEBHOOK_BLOCK_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),         # ULA IPv6
    ipaddress.ip_network("fe80::/10"),        # link-local IPv6
]
_WEBHOOK_ALLOWED_SCHEMES = {"https", "http"}   # http allow for internal test, https strongly preferred

def _validate_webhook_url(url: str) -> tuple:
    """
    OXW-2026-017 + DNS-Rebinding fix:
    URL'nin iÃ§ aÄŸa yÃ¶nlenmediÄŸini doÄŸrula.
    DNS'i burada Ã§Ã¶z, resolved IP'yi dÃ¶ndÃ¼r â†’ caller IP'yi direkt kullanÄ±r,
    ikinci DNS Ã§Ã¶zÃ¼mleme (rebinding penceresi) olmaz.
    Returns: (ok: bool, reason: str, resolved_ip: str)
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in _WEBHOOK_ALLOWED_SCHEMES:
            return False, f"Ä°zinsiz ÅŸema: {parsed.scheme}", ""
        hostname = parsed.hostname or ""
        if not hostname:
            return False, "Host bulunamadÄ±", ""
        try:
            resolved_ip_str = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(resolved_ip_str)
        except Exception:
            return False, f"Host Ã§Ã¶zÃ¼lemedi: {hostname}", ""
        if any(ip in net for net in _WEBHOOK_BLOCK_NETS):
            return False, f"Ä°Ã§ aÄŸ/loopback hedefi engellendi: {ip}", ""
        return True, "", resolved_ip_str
    except Exception as e:
        return False, str(e), ""


def _build_pinned_url(url: str, resolved_ip: str) -> tuple:
    """
    DNS-rebinding korumasÄ±: hostname'i Ã§Ã¶zÃ¼lmÃ¼ÅŸ IP ile deÄŸiÅŸtir.
    HTTP iÃ§in: IP'yi direkt URL'e koy, Host header ekle.
    HTTPS iÃ§in: TLS SNI sorununa yol aÃ§ar, hostname koru ama
                allow_redirects=False + tekrar doÄŸrulama yap.
    Returns: (pinned_url, host_header)
    """
    parsed  = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme == "http" and resolved_ip:
        # HTTP: IP ile deÄŸiÅŸtir, Host header ile orijinal hostname geÃ§
        port_part = f":{parsed.port}" if parsed.port else ""
        pinned = url.replace(f"//{hostname}", f"//{resolved_ip}{port_part}", 1)
        return pinned, hostname
    # HTTPS: TLS cert hostname eÅŸleÅŸmesi iÃ§in hostname koru, Host header None
    return url, ""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load():
    if not os.path.isfile(WEBHOOKS_FILE):
        return {}
    try:
        with open(WEBHOOKS_FILE) as f:
            return json.load(f)
    except Exception as exc:
        log.error("_load webhooks error: %s", exc)
        return {}


def _save(data):
    try:
        os.makedirs(os.path.dirname(WEBHOOKS_FILE), exist_ok=True)
        with open(WEBHOOKS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        log.error("_save webhooks error: %s", exc)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def register(name, url, events, secret=""):
    """
    Register a new webhook.

    Args:
        name   (str): Human-friendly label.
        url    (str): Target URL.
        events (list[str]): List of event names to subscribe to.
        secret (str): Optional HMAC secret.

    Returns:
        dict: The created webhook record.
    """
    invalid = [e for e in events if e not in SUPPORTED_EVENTS]
    if invalid:
        log.warning("register: unknown events ignored: %s", invalid)
        events = [e for e in events if e in SUPPORTED_EVENTS]

    webhook_id = str(uuid.uuid4())
    record = {
        "id":         webhook_id,
        "name":       name,
        "url":        url,
        "events":     events,
        "secret":     secret,
        "active":     True,
        "created_at": time.time(),
    }
    with _lock:
        data = _load()
        data[webhook_id] = record
        _save(data)

    log.info("Webhook registered: %s (%s)", name, webhook_id)
    return record


def list_webhooks():
    """Return all registered webhooks."""
    with _lock:
        return list(_load().values())


def get_webhook(webhook_id):
    """Return a single webhook by ID, or None."""
    with _lock:
        return _load().get(webhook_id)


def update_webhook(webhook_id, **kwargs):
    """
    Update webhook fields (name, url, events, secret, active).

    Returns:
        dict: Updated record, or None if not found.
    """
    with _lock:
        data = _load()
        if webhook_id not in data:
            return None
        allowed = {"name", "url", "events", "secret", "active"}
        for k, v in kwargs.items():
            if k in allowed:
                data[webhook_id][k] = v
        _save(data)
        return data[webhook_id]


def delete_webhook(webhook_id):
    """Delete a webhook by ID. Returns True if deleted, False if not found."""
    with _lock:
        data = _load()
        if webhook_id not in data:
            return False
        del data[webhook_id]
        _save(data)
    log.info("Webhook deleted: %s", webhook_id)
    return True


# ---------------------------------------------------------------------------
# Triggering
# ---------------------------------------------------------------------------

def trigger(event_name, payload):
    """
    Dispatch *payload* to all active webhooks subscribed to *event_name*.

    Deliveries are performed asynchronously in daemon threads.

    Args:
        event_name (str): One of SUPPORTED_EVENTS.
        payload    (dict): Arbitrary JSON-serialisable data.
    """
    if event_name not in SUPPORTED_EVENTS:
        log.warning("trigger: unknown event '%s'", event_name)

    webhooks = list_webhooks()
    for wh in webhooks:
        if not wh.get("active", True):
            continue
        if event_name not in wh.get("events", []):
            continue
        t = threading.Thread(
            target=_send,
            args=(wh, event_name, payload),
            daemon=True,
            name=f"webhook-{wh['id'][:8]}",
        )
        t.start()


def _send(webhook, event_name, payload):
    """
    POST payload to a single webhook with HMAC-SHA256 signature.
    Logs the delivery result.

    DNS-Rebinding korumasÄ±: DNS'i burada tek sefer Ã§Ã¶z, resolved IP ile request at.
    Bu sayede validate â†’ request arasÄ±nda DNS deÄŸiÅŸse bile (TTL=0 rebinding) saldÄ±rÄ± bloke.
    """
    url    = webhook["url"]
    # OXW-2026-017 + DNS-Rebinding fix: SSRF kontrolÃ¼ + tek sefer DNS Ã§Ã¶zÃ¼mle
    valid, reason, resolved_ip = _validate_webhook_url(url)
    if not valid:
        log.warning("Webhook SSRF engellendi [%s] %s: %s", webhook["id"], url, reason)
        _log_delivery(webhook_id=webhook["id"], event=event_name, url=url,
                      status_code=None, success=False, error=f"SSRF engellendi: {reason}")
        return

    # DNS rebinding: resolved IP'yi kullan, hostname'i Host header'a taÅŸÄ±
    pinned_url, host_hdr = _build_pinned_url(url, resolved_ip)

    secret = webhook.get("secret", "")
    body   = json.dumps({
        "event":   event_name,
        "payload": payload,
        "ts":      time.time(),
    }).encode()

    sig = hmac.new(
        secret.encode() if secret else b"",
        body,
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type":       "application/json",
        "X-ankavm-Event":     event_name,
        "X-ankavm-Signature": f"sha256={sig}",
        "X-ankavm-Hook-ID":   webhook["id"],
    }
    if host_hdr:
        headers["Host"] = host_hdr

    status_code = None
    success     = False
    error       = ""

    try:
        if _HAS_REQUESTS:
            # allow_redirects=False: redirect hedefi ayrÄ±ca doÄŸrulanamaz â†’ kapat
            resp = _req.post(pinned_url, data=body, headers=headers,
                             timeout=10, allow_redirects=False)
            status_code = resp.status_code
            success     = 200 <= status_code < 300
        else:
            req = urllib.request.Request(pinned_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                status_code = resp.status
                success     = True
    except Exception as exc:
        error = str(exc)
        log.warning("Webhook delivery failed [%s] %s: %s",
                    webhook["id"], url, exc)

    _log_delivery(
        webhook_id=webhook["id"],
        event=event_name,
        url=url,
        status_code=status_code,
        success=success,
        error=error,
    )


# ---------------------------------------------------------------------------
# Delivery logging
# ---------------------------------------------------------------------------

def _log_delivery(webhook_id, event, url, status_code, success, error=""):
    """Append a JSONL delivery record to DELIVERY_LOG."""
    record = {
        "ts":          time.time(),
        "webhook_id":  webhook_id,
        "event":       event,
        "url":         url,
        "status_code": status_code,
        "success":     success,
        "error":       error,
    }
    try:
        os.makedirs(os.path.dirname(DELIVERY_LOG), exist_ok=True)
        with _delivery_lock:
            with open(DELIVERY_LOG, "a") as f:
                f.write(json.dumps(record) + "\n")
    except Exception as exc:
        log.error("_log_delivery error: %s", exc)


def get_deliveries(webhook_id, limit=50):
    """
    Return the last *limit* delivery records for a specific webhook.

    Returns:
        list[dict]
    """
    if not os.path.isfile(DELIVERY_LOG):
        return []
    records = []
    try:
        with open(DELIVERY_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("webhook_id") == webhook_id:
                        records.append(rec)
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        log.error("get_deliveries error: %s", exc)
    return records[-limit:]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_webhook(webhook_id):
    """
    Send a test ping to the specified webhook.

    Returns:
        dict: success, status_code, error
    """
    wh = get_webhook(webhook_id)
    if wh is None:
        return {"success": False, "status_code": None,
                "error": f"Webhook '{webhook_id}' not found"}

    payload = {"message": "ankavm webhook test ping", "ts": time.time()}
    # Trigger synchronously for immediate feedback
    url    = wh["url"]

    # OXW-2026-017 + DNS-Rebinding fix: test_webhook'ta da SSRF + DNS pin kontrolÃ¼
    valid, ssrf_reason, resolved_ip = _validate_webhook_url(url)
    if not valid:
        log.warning("Webhook test SSRF engellendi [%s] %s: %s", webhook_id, url, ssrf_reason)
        _log_delivery(webhook_id, "test.ping", url, None, False, f"SSRF engellendi: {ssrf_reason}")
        return {"success": False, "status_code": None, "error": f"SSRF engellendi: {ssrf_reason}"}

    pinned_url, host_hdr = _build_pinned_url(url, resolved_ip)

    secret = wh.get("secret", "")
    body   = json.dumps({
        "event":   "test.ping",
        "payload": payload,
        "ts":      time.time(),
    }).encode()
    sig = hmac.new(
        secret.encode() if secret else b"",
        body,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type":       "application/json",
        "X-ankavm-Event":     "test.ping",
        "X-ankavm-Signature": f"sha256={sig}",
        "X-ankavm-Hook-ID":   webhook_id,
    }
    if host_hdr:
        headers["Host"] = host_hdr

    status_code = None
    error       = ""
    try:
        if _HAS_REQUESTS:
            resp = _req.post(pinned_url, data=body, headers=headers,
                             timeout=10, allow_redirects=False)
            status_code = resp.status_code
            success     = 200 <= status_code < 300
        else:
            req = urllib.request.Request(pinned_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                status_code = resp.status
                success     = True
    except Exception as exc:
        error   = str(exc)
        success = False

    _log_delivery(webhook_id, "test.ping", url, status_code, success, error)
    return {"success": success, "status_code": status_code, "error": error}






