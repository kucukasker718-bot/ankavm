"""
nginx_manager.py — nginx/OpenResty reverse proxy management
ankavm Hypervisor backend module

OpenResty (openresty) is preferred when available — it supports Lua scripting
via ngx_http_lua_module. Falls back to plain nginx automatically.
"""

import subprocess
import json
import logging
import os
import threading
import re
import shutil

log = logging.getLogger("ankavm.nginx")

SITES_DIR   = "/etc/nginx/sites-available"
ENABLED_DIR = "/etc/nginx/sites-enabled"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# OpenResty / Nginx detection
# ---------------------------------------------------------------------------

def _detect_binary() -> str:
    """openresty varsa openresty, yoksa nginx döner."""
    if shutil.which("openresty"):
        return "openresty"
    return "nginx"


def _detect_sites_dirs() -> tuple:
    """
    OpenResty ve nginx config dizinlerini tespit et.
    Döner: (sites_available, sites_enabled)
    """
    # OpenResty default locations
    for base in ("/usr/local/openresty/nginx/conf",
                 "/etc/openresty"):
        avail = os.path.join(base, "sites-available")
        enabl = os.path.join(base, "sites-enabled")
        if os.path.isdir(avail):
            return avail, enabl
    # Fallback: standard nginx
    return "/etc/nginx/sites-available", "/etc/nginx/sites-enabled"


BINARY = _detect_binary()
SITES_DIR, ENABLED_DIR = _detect_sites_dirs()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_status():
    """
    Return nginx/openresty service status.

    Returns:
        dict: active, version, config_ok, binary, openresty
    """
    active = False
    version = None
    config_ok = False
    svc_name = "openresty" if BINARY == "openresty" else "nginx"

    try:
        r = subprocess.run(
            ["systemctl", "is-active", svc_name],
            capture_output=True, text=True, timeout=10
        )
        active = r.stdout.strip() == "active"
    except Exception as exc:
        log.warning("systemctl is-active %s failed: %s", svc_name, exc)

    try:
        r = subprocess.run(
            [BINARY, "-v"],
            capture_output=True, text=True, timeout=10
        )
        m = re.search(r"nginx/(\S+)", r.stderr + r.stdout)
        if m:
            version = m.group(1)
    except Exception as exc:
        log.warning("%s -v failed: %s", BINARY, exc)

    config_ok_result = test_config()
    config_ok = config_ok_result.get("ok", False)

    return {
        "active":    active,
        "version":   version,
        "config_ok": config_ok,
        "binary":    BINARY,
        "openresty": BINARY == "openresty",
    }


# ---------------------------------------------------------------------------
# Site management
# ---------------------------------------------------------------------------

def list_sites():
    """
    List all sites in sites-available, marking enabled ones.

    Returns:
        list[dict]: name, enabled, config (raw text)
    """
    if not os.path.isdir(SITES_DIR):
        log.warning("sites-available directory not found: %s", SITES_DIR)
        return []

    enabled_names = set()
    if os.path.isdir(ENABLED_DIR):
        for entry in os.listdir(ENABLED_DIR):
            enabled_names.add(entry)

    sites = []
    for name in sorted(os.listdir(SITES_DIR)):
        path = os.path.join(SITES_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                config = f.read()
        except Exception:
            config = ""
        sites.append({
            "name":    name,
            "enabled": name in enabled_names,
            "config":  config,
        })
    return sites


def get_site(name):
    """Return site dict for *name*, or None if not found."""
    path = os.path.join(SITES_DIR, name)
    if not os.path.isfile(path):
        return None
    enabled_path = os.path.join(ENABLED_DIR, name)
    try:
        with open(path) as f:
            config = f.read()
    except Exception as exc:
        log.error("get_site read error: %s", exc)
        config = ""
    return {
        "name":    name,
        "enabled": os.path.exists(enabled_path),
        "config":  config,
    }


def _sanitize_nginx_token(value: str, field: str = "value") -> str:
    """rapor #61 fix: nginx config injection önleme.
    server_name, upstream_host, proxy_pass gibi alanlara
    yalnızca güvenli karakterler geçer. Newline, ';', '{', '}' yasak.
    """
    import re as _re
    if not value:
        raise ValueError(f"nginx config: {field} boş olamaz")
    # Sadece hostname/IP karakterlerine izin ver: harf, rakam, nokta, tire, alt çizgi, iki nokta, köşeli parantez
    if not _re.match(r'^[a-zA-Z0-9._:\-\[\]]+$', value):
        raise ValueError(f"nginx config: {field} geçersiz karakter içeriyor: {value!r}")
    return value

def create_site(name, server_name, upstream_host, upstream_port,
                ssl=False, ssl_cert=None, ssl_key=None,
                websocket=False, extra_locations=None):
    """
    Generate an nginx config and write it to sites-available.

    Returns:
        dict: success, message, path
    """
    # rapor #61 fix: injection sanitize
    try:
        server_name   = _sanitize_nginx_token(server_name, "server_name")
        upstream_host = _sanitize_nginx_token(upstream_host, "upstream_host")
    except ValueError as e:
        return {"success": False, "message": str(e), "path": None}
    config = _generate_config(
        name, server_name, upstream_host, upstream_port,
        ssl, ssl_cert, ssl_key, websocket, extra_locations or []
    )
    path = os.path.join(SITES_DIR, name)
    try:
        os.makedirs(SITES_DIR, exist_ok=True)
        with _lock:
            with open(path, "w") as f:
                f.write(config)
        log.info("nginx site created: %s", name)
        return {"success": True, "message": "Site created", "path": path}
    except Exception as exc:
        log.exception("create_site error: %s", exc)
        return {"success": False, "message": str(exc), "path": None}


def enable_site(name):
    """Symlink site into sites-enabled."""
    src  = os.path.join(SITES_DIR, name)
    dest = os.path.join(ENABLED_DIR, name)
    if not os.path.isfile(src):
        return {"success": False, "message": f"Site '{name}' not found in sites-available"}
    try:
        os.makedirs(ENABLED_DIR, exist_ok=True)
        if not os.path.exists(dest):
            os.symlink(src, dest)
        log.info("nginx site enabled: %s", name)
        return {"success": True, "message": f"Site '{name}' enabled"}
    except Exception as exc:
        log.exception("enable_site error: %s", exc)
        return {"success": False, "message": str(exc)}


def disable_site(name):
    """Remove symlink from sites-enabled."""
    dest = os.path.join(ENABLED_DIR, name)
    try:
        if os.path.exists(dest) or os.path.islink(dest):
            os.unlink(dest)
            log.info("nginx site disabled: %s", name)
        return {"success": True, "message": f"Site '{name}' disabled"}
    except Exception as exc:
        log.exception("disable_site error: %s", exc)
        return {"success": False, "message": str(exc)}


def delete_site(name):
    """Disable and permanently remove a site config."""
    disable_site(name)
    path = os.path.join(SITES_DIR, name)
    try:
        if os.path.isfile(path):
            os.unlink(path)
            log.info("nginx site deleted: %s", name)
        return {"success": True, "message": f"Site '{name}' deleted"}
    except Exception as exc:
        log.exception("delete_site error: %s", exc)
        return {"success": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Reload / test
# ---------------------------------------------------------------------------

def reload():
    """Test config then reload nginx/openresty. Returns dict with success and output."""
    svc_name = "openresty" if BINARY == "openresty" else "nginx"
    test = test_config()
    if not test.get("ok"):
        return {"success": False, "output": test.get("output", "Config test failed")}
    try:
        r = subprocess.run(
            ["systemctl", "reload", svc_name],
            capture_output=True, text=True, timeout=30
        )
        success = r.returncode == 0
        output  = (r.stdout + r.stderr).strip()
        if success:
            log.info("%s reloaded", svc_name)
        else:
            log.warning("%s reload failed: %s", svc_name, output)
        return {"success": success, "output": output}
    except Exception as exc:
        log.exception("reload error: %s", exc)
        return {"success": False, "output": str(exc)}


def test_config():
    """Run ``nginx -t`` / ``openresty -t`` and return {ok, output}."""
    try:
        r = subprocess.run(
            [BINARY, "-t"],
            capture_output=True, text=True, timeout=15
        )
        ok = r.returncode == 0
        return {"ok": ok, "output": (r.stdout + r.stderr).strip()}
    except FileNotFoundError:
        return {"ok": False, "output": f"{BINARY} not found"}
    except Exception as exc:
        log.exception("test_config error: %s", exc)
        return {"ok": False, "output": str(exc)}


# ---------------------------------------------------------------------------
# Location management
# ---------------------------------------------------------------------------

def add_location(site_name, path, proxy_pass, extra=""):
    """
    Append a new ``location`` block to an existing site config.

    Returns:
        dict: success, message
    """
    site = get_site(site_name)
    if site is None:
        return {"success": False, "message": f"Site '{site_name}' not found"}

    location_block = (
        f"\n    location {path} {{\n"
        f"        proxy_pass {proxy_pass};\n"
        f"        proxy_set_header Host $host;\n"
        f"        proxy_set_header X-Real-IP $remote_addr;\n"
    )
    if extra:
        location_block += f"        {extra}\n"
    location_block += "    }\n"

    config = site["config"]
    # Insert before the closing brace of the last server block
    insert_pos = config.rfind("}")
    if insert_pos == -1:
        return {"success": False, "message": "Could not find closing brace in config"}

    new_config = config[:insert_pos] + location_block + config[insert_pos:]
    site_path  = os.path.join(SITES_DIR, site_name)
    try:
        with _lock:
            with open(site_path, "w") as f:
                f.write(new_config)
        log.info("Location %s added to site %s", path, site_name)
        return {"success": True, "message": f"Location '{path}' added"}
    except Exception as exc:
        log.exception("add_location error: %s", exc)
        return {"success": False, "message": str(exc)}


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def generate_lua_middleware(rate_limit_rps: int = 20,
                           auth_token: str = "",
                           block_ips: list = None) -> str:
    """
    OpenResty Lua middleware bloğu üret (access_by_lua_block).
    Özellikler: rate limiting, Bearer token kontrolü, IP bloklama.
    nginx'te lua desteği yoksa bu blok atlanmalı.
    """
    block_ips = block_ips or []
    blocked_set = (
        "local blocked = {" +
        ", ".join(f'["{ip}"]=true' for ip in block_ips) +
        "}\n" if block_ips else "local blocked = {}\n"
    )

    auth_check = ""
    if auth_token:
        auth_check = f"""
        local auth = ngx.req.get_headers()["Authorization"] or ""
        if auth ~= "Bearer {auth_token}" then
            ngx.status = 401
            ngx.header["WWW-Authenticate"] = 'Bearer realm="ankavm"'
            ngx.say('{{"error":"Unauthorized"}}')
            return ngx.exit(401)
        end"""

    lua_block = f"""
    access_by_lua_block {{
        local ip = ngx.var.remote_addr
        {blocked_set}
        if blocked[ip] then
            ngx.status = 403
            ngx.say('{{"error":"Forbidden"}}')
            return ngx.exit(403)
        end
        {auth_check}
        -- Rate limit: {rate_limit_rps} req/s per IP
        local limit = require("resty.limit.req")
        local lim, err = limit.new("ankavm_rate_limit", {rate_limit_rps}, {rate_limit_rps * 2})
        if lim then
            local _, err2 = lim:incoming(ip, true)
            if err2 == "rejected" then
                ngx.status = 429
                ngx.say('{{"error":"Rate limit exceeded"}}')
                return ngx.exit(429)
            end
        end
    }}
"""
    return lua_block


def _generate_config(name, server_name, upstream_host, upstream_port,
                     ssl, ssl_cert, ssl_key, websocket, extra_locations,
                     lua_middleware: str = ""):
    """Build and return an nginx/openresty server config string."""
    listen_plain = "80"
    listen_ssl   = "443 ssl"
    upstream_def = (
        f"upstream {name}_backend {{\n"
        f"    server {upstream_host}:{upstream_port};\n"
        f"}}\n\n"
    )

    ws_headers = ""
    if websocket:
        ws_headers = (
            "        proxy_http_version 1.1;\n"
            "        proxy_set_header Upgrade $http_upgrade;\n"
            "        proxy_set_header Connection \"Upgrade\";\n"
        )

    ssl_block = ""
    if ssl and ssl_cert and ssl_key:
        ssl_block = (
            f"    ssl_certificate     {ssl_cert};\n"
            f"    ssl_certificate_key {ssl_key};\n"
            f"    ssl_protocols       TLSv1.2 TLSv1.3;\n"
            f"    ssl_ciphers         HIGH:!aNULL:!MD5;\n"
        )

    extra_loc_blocks = ""
    for loc in extra_locations:
        loc_path  = loc.get("path", "/extra")
        loc_proxy = loc.get("proxy_pass", f"http://{name}_backend")
        extra_loc_blocks += (
            f"    location {loc_path} {{\n"
            f"        proxy_pass {loc_proxy};\n"
            f"    }}\n"
        )

    listen_directive = (
        f"    listen {listen_ssl};\n{ssl_block}" if ssl
        else f"    listen {listen_plain};\n"
    )

    config = (
        f"# ankavm {'openresty' if BINARY == 'openresty' else 'nginx'} config: {name}\n"
        + upstream_def
        + f"server {{\n"
        + listen_directive
        + f"    server_name {server_name};\n\n"
        + f"    location / {{\n"
        + lua_middleware
        + f"        proxy_pass http://{name}_backend;\n"
        + f"        proxy_set_header Host $host;\n"
        + f"        proxy_set_header X-Real-IP $remote_addr;\n"
        + f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        + f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
        + ws_headers
        + f"    }}\n"
        + extra_loc_blocks
        + f"}}\n"
    )

    # HTTP → HTTPS redirect when SSL is enabled
    if ssl:
        config += (
            f"\nserver {{\n"
            f"    listen {listen_plain};\n"
            f"    server_name {server_name};\n"
            f"    return 301 https://$host$request_uri;\n"
            f"}}\n"
        )

    return config






