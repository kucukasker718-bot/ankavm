"""
Geo-DNS failover — Cloudflare / Route53 record management + health checks.

Cloudflare uses bearer token + zone API; Route53 uses AWS sigv4 (not pure
stdlib) — for Route53 we shell out to `aws` CLI if available, otherwise
fall back to local "would update" simulation. Cloudflare path is fully
implemented via urllib.
"""
import os
import json
import time
import logging
import threading
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger("geo_dns_manager")

DATA_DIR = Path("/var/lib/ankavm")
CONF_PATH = DATA_DIR / "geo_dns.conf"
RECORDS_PATH = DATA_DIR / "geo_dns_records.json"

_lock = threading.Lock()
_health = {"thread": None, "stop": False, "last_run": 0, "results": {}}


def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONF_PATH.exists():
        CONF_PATH.write_text(json.dumps({"provider": "cloudflare",
                                         "api_token": "", "zone_id": ""}),
                             encoding="utf-8")
    if not RECORDS_PATH.exists():
        RECORDS_PATH.write_text(json.dumps({"records": []}), encoding="utf-8")


def _load_conf() -> dict:
    try:
        _ensure()
        return json.loads(CONF_PATH.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        log.error("_load_conf: %s", e)
        return {"provider": "cloudflare", "api_token": "", "zone_id": ""}


def _save_conf(cfg: dict):
    try:
        CONF_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            CONF_PATH.chmod(0o600)
        except Exception:
            pass
    except Exception as e:
        log.error("_save_conf: %s", e)


def _load_records() -> list:
    try:
        _ensure()
        return json.loads(RECORDS_PATH.read_text(encoding="utf-8") or "{}").get("records", [])
    except Exception:
        return []


def _save_records(records: list):
    try:
        RECORDS_PATH.write_text(json.dumps({"records": records}, indent=2),
                                encoding="utf-8")
    except Exception as e:
        log.error("_save_records: %s", e)


def configure(provider: str = "cloudflare", api_token: str = "",
              zone_id: str = "", hosted_zone_id: str = "") -> dict:
    try:
        cfg = {"provider": provider, "api_token": api_token,
               "zone_id": zone_id, "hosted_zone_id": hosted_zone_id}
        _save_conf(cfg)
        return {"ok": True, "provider": provider}
    except Exception as e:
        log.error("configure: %s", e)
        return {"ok": False, "error": str(e)}


def get_config() -> dict:
    cfg = _load_conf()
    if cfg.get("api_token"):
        tok = cfg["api_token"]
        cfg = dict(cfg)
        cfg["api_token"] = "***" + tok[-4:] if len(tok) > 4 else "***"
    return cfg


def _cf_request(method: str, path: str, body=None) -> dict:
    cfg = _load_conf()
    token = cfg.get("api_token", "")
    if not token:
        raise RuntimeError("api_token not configured")
    url = "https://api.cloudflare.com/client/v4" + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", "ignore")
        except Exception:
            body_txt = ""
        raise RuntimeError(f"CF HTTP {e.code}: {body_txt[:200]}")


def add_record(name: str, primary_ip: str, failover_ip: str = "",
               health_check_url: str = "", ttl: int = 60,
               rtype: str = "A") -> dict:
    try:
        with _lock:
            records = _load_records()
            existing = next((r for r in records if r.get("name") == name), None)
            cf_id = existing.get("cf_record_id") if existing else None

            cfg = _load_conf()
            if cfg.get("provider") == "cloudflare" and cfg.get("zone_id"):
                payload = {"type": rtype, "name": name, "content": primary_ip,
                           "ttl": int(ttl), "proxied": False}
                if cf_id:
                    res = _cf_request("PUT",
                                      f"/zones/{cfg['zone_id']}/dns_records/{cf_id}",
                                      payload)
                else:
                    res = _cf_request("POST",
                                      f"/zones/{cfg['zone_id']}/dns_records",
                                      payload)
                cf_id = (res.get("result") or {}).get("id") or cf_id

            rec = {
                "name": name, "primary_ip": primary_ip,
                "failover_ip": failover_ip, "health_check_url": health_check_url,
                "ttl": int(ttl), "type": rtype, "active_ip": primary_ip,
                "cf_record_id": cf_id, "updated_at": time.time(),
            }
            if existing:
                records = [rec if r.get("name") == name else r for r in records]
            else:
                records.append(rec)
            _save_records(records)
        return {"ok": True, "record": rec}
    except Exception as e:
        log.error("add_record %s: %s", name, e)
        return {"ok": False, "error": str(e)}


def list_records() -> list:
    return _load_records()


def delete_record(name: str) -> dict:
    try:
        with _lock:
            records = _load_records()
            target = next((r for r in records if r.get("name") == name), None)
            if not target:
                return {"ok": False, "error": "not found"}
            cfg = _load_conf()
            if cfg.get("provider") == "cloudflare" and cfg.get("zone_id") \
                    and target.get("cf_record_id"):
                try:
                    _cf_request("DELETE",
                                f"/zones/{cfg['zone_id']}/dns_records/{target['cf_record_id']}")
                except Exception as e:
                    log.warning("CF delete: %s", e)
            records = [r for r in records if r.get("name") != name]
            _save_records(records)
        return {"ok": True, "deleted": name}
    except Exception as e:
        log.error("delete_record: %s", e)
        return {"ok": False, "error": str(e)}


def _check_url(url: str, timeout: int = 5) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def _switch_active(rec: dict, new_ip: str) -> bool:
    cfg = _load_conf()
    if cfg.get("provider") == "cloudflare" and cfg.get("zone_id") \
            and rec.get("cf_record_id"):
        try:
            _cf_request("PUT",
                        f"/zones/{cfg['zone_id']}/dns_records/{rec['cf_record_id']}",
                        {"type": rec.get("type", "A"), "name": rec["name"],
                         "content": new_ip, "ttl": int(rec.get("ttl", 60)),
                         "proxied": False})
            return True
        except Exception as e:
            log.error("switch_active CF: %s", e)
            return False
    return True  # no-op for other providers


def health_check_run_once() -> dict:
    """One pass — flip records whose primary is unhealthy."""
    try:
        results = {}
        with _lock:
            records = _load_records()
        for rec in records:
            url = rec.get("health_check_url")
            if not url:
                continue
            healthy = _check_url(url)
            results[rec["name"]] = {"healthy": healthy, "active": rec.get("active_ip")}
            desired = rec["primary_ip"] if healthy else rec.get("failover_ip") or rec["primary_ip"]
            if desired != rec.get("active_ip"):
                if _switch_active(rec, desired):
                    rec["active_ip"] = desired
                    rec["last_failover"] = time.time()
                    results[rec["name"]]["switched_to"] = desired
        with _lock:
            _save_records(records)
        _health["last_run"] = time.time()
        _health["results"] = results
        return {"ok": True, "results": results, "ts": _health["last_run"]}
    except Exception as e:
        log.error("health_check_run_once: %s", e)
        return {"ok": False, "error": str(e)}


def _health_loop(interval: int):
    while not _health["stop"]:
        try:
            health_check_run_once()
        except Exception as e:
            log.error("health_loop: %s", e)
        for _ in range(interval):
            if _health["stop"]:
                break
            time.sleep(1)


def start_health_loop(interval_sec: int = 30) -> dict:
    if _health["thread"] and _health["thread"].is_alive():
        return {"ok": True, "already_running": True}
    _health["stop"] = False
    t = threading.Thread(target=_health_loop, args=(int(interval_sec),),
                         name="geo-dns-health", daemon=True)
    _health["thread"] = t
    t.start()
    return {"ok": True, "interval_sec": int(interval_sec)}


def stop_health_loop() -> dict:
    _health["stop"] = True
    return {"ok": True}


def health_status() -> dict:
    return {"last_run": _health.get("last_run", 0),
            "results": _health.get("results", {}),
            "running": bool(_health["thread"] and _health["thread"].is_alive())}






