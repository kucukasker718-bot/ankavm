"""
HashiCorp Vault integration — KV v2 secret read/write/list via HTTP API.
Pure stdlib, no hvac dependency.
"""
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

log = logging.getLogger("vault_integration")

CONF_DIR = Path("/etc/ankavm")
CONF_PATH = CONF_DIR / "vault.conf"


def _load() -> dict:
    try:
        if CONF_PATH.exists():
            return json.loads(CONF_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("vault conf load: %s", e)
    return {"url": "", "token": "", "mount_path": "secret/", "verify_ssl": True}


def _save(cfg: dict) -> None:
    try:
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        CONF_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            CONF_PATH.chmod(0o600)
        except Exception:
            pass
    except Exception as e:
        log.error("vault conf save: %s", e)
        raise


def _req(method: str, path: str, body=None, timeout: int = 10):
    cfg = _load()
    if not cfg.get("url"):
        raise RuntimeError("Vault not configured")
    url = cfg["url"].rstrip("/") + "/v1/" + path.lstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Vault-Token", cfg.get("token", ""))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8") or "{}"
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", "ignore")
        except Exception:
            body_txt = ""
        raise RuntimeError(f"Vault HTTP {e.code}: {body_txt[:200]}")


def configure_vault(url: str, token: str, mount_path: str = "secret/",
                    verify_ssl: bool = True) -> dict:
    cfg = {"url": url, "token": token, "mount_path": mount_path,
           "verify_ssl": bool(verify_ssl)}
    _save(cfg)
    return {"ok": True, "url": url, "mount_path": mount_path}


def get_config() -> dict:
    cfg = _load()
    # Hide token
    if cfg.get("token"):
        cfg = dict(cfg)
        cfg["token"] = "***" + cfg["token"][-4:] if len(cfg["token"]) > 4 else "***"
    return cfg


def read_secret(path: str) -> dict:
    """KV v2 read: <mount>/data/<path>."""
    try:
        cfg = _load()
        mount = cfg.get("mount_path", "secret/").rstrip("/")
        full = f"{mount}/data/{path.lstrip('/')}"
        r = _req("GET", full)
        return {"ok": True, "data": (r.get("data") or {}).get("data", {}),
                "metadata": (r.get("data") or {}).get("metadata", {})}
    except Exception as e:
        log.error("read_secret %s: %s", path, e)
        return {"ok": False, "error": str(e), "data": {}}


def write_secret(path: str, data: dict) -> dict:
    try:
        cfg = _load()
        mount = cfg.get("mount_path", "secret/").rstrip("/")
        full = f"{mount}/data/{path.lstrip('/')}"
        r = _req("POST", full, body={"data": data})
        return {"ok": True, "version": (r.get("data") or {}).get("version")}
    except Exception as e:
        log.error("write_secret %s: %s", path, e)
        return {"ok": False, "error": str(e)}


def delete_secret(path: str) -> dict:
    try:
        cfg = _load()
        mount = cfg.get("mount_path", "secret/").rstrip("/")
        full = f"{mount}/metadata/{path.lstrip('/')}"
        _req("DELETE", full)
        return {"ok": True}
    except Exception as e:
        log.error("delete_secret %s: %s", path, e)
        return {"ok": False, "error": str(e)}


def list_secrets(path: str = "") -> dict:
    """KV v2 list: GET <mount>/metadata/<path>?list=true."""
    try:
        cfg = _load()
        mount = cfg.get("mount_path", "secret/").rstrip("/")
        full = f"{mount}/metadata/{path.lstrip('/')}?list=true"
        r = _req("GET", full)
        return {"ok": True, "keys": (r.get("data") or {}).get("keys", [])}
    except Exception as e:
        log.error("list_secrets %s: %s", path, e)
        return {"ok": False, "error": str(e), "keys": []}


def test_connection() -> dict:
    try:
        r = _req("GET", "sys/health")
        return {"ok": True, "initialized": r.get("initialized"),
                "sealed": r.get("sealed"), "version": r.get("version")}
    except Exception as e:
        return {"ok": False, "error": str(e)}






