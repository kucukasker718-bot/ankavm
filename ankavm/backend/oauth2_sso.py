"""
ankavm OAuth 2.0 Manager (Enterprise SSO)
Adds OAuth 2.0 authorization-code flow with PKCE.
Provider presets: Google Workspace, Microsoft Entra ID (Azure AD),
GitHub, GitLab, Bitbucket, Okta, Auth0, Keycloak, generic OIDC-compatible.

Config: /var/lib/ankavm/oauth2_config.json
State: in-memory dict with TTL (10 min) keyed by `state` parameter
Audit: /var/log/ankavm/oauth2_audit.jsonl

Flow:
  1. GET /api/auth/oauth2/<provider>/start  -> returns authorization URL with PKCE challenge
  2. User -> IdP -> callback with code+state
  3. GET /api/auth/oauth2/<provider>/callback?code=...&state=...
  4. Backend exchanges code for token (server-side, never exposes client_secret to browser)
  5. Backend fetches userinfo, maps email -> ankavm user, creates session JWT
  6. Returns ankavm JWT to redirect URL
"""

import os
import json
import time
import ssl
import secrets
import hashlib
import base64
import threading
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

CONFIG_PATH = "/var/lib/ankavm/oauth2_config.json"
AUDIT_PATH = "/var/log/ankavm/oauth2_audit.jsonl"
STATE_TTL = 600  # 10 minutes
HTTP_TIMEOUT = 15

_state_store: dict = {}
_state_lock = threading.Lock()
_cfg_lock = threading.Lock()

PROVIDERS = {
    "google": {
        "display_name": "Google Workspace",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "userinfo_endpoint": "https://openidconnect.googleapis.com/v1/userinfo",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
    },
    "microsoft": {
        "display_name": "Microsoft Entra ID",
        "authorization_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
        "default_scopes": ["openid", "email", "profile", "User.Read"],
        "email_claim": "email",
        "name_claim": "name",
        "tenant_aware": True,
        "default_tenant": "organizations",
    },
    "github": {
        "display_name": "GitHub",
        "authorization_endpoint": "https://github.com/login/oauth/authorize",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "userinfo_endpoint": "https://api.github.com/user",
        "default_scopes": ["read:user", "user:email"],
        "email_claim": "email",
        "name_claim": "name",
    },
    "gitlab": {
        "display_name": "GitLab",
        "authorization_endpoint": "https://gitlab.com/oauth/authorize",
        "token_endpoint": "https://gitlab.com/oauth/token",
        "userinfo_endpoint": "https://gitlab.com/oauth/userinfo",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
    },
    "bitbucket": {
        "display_name": "Bitbucket",
        "authorization_endpoint": "https://bitbucket.org/site/oauth2/authorize",
        "token_endpoint": "https://bitbucket.org/site/oauth2/access_token",
        "userinfo_endpoint": "https://api.bitbucket.org/2.0/user",
        "default_scopes": ["account", "email"],
        "email_claim": "email",
        "name_claim": "display_name",
    },
    "okta": {
        "display_name": "Okta",
        "authorization_endpoint": "https://{tenant}/oauth2/default/v1/authorize",
        "token_endpoint": "https://{tenant}/oauth2/default/v1/token",
        "userinfo_endpoint": "https://{tenant}/oauth2/default/v1/userinfo",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
        "tenant_aware": True,
    },
    "auth0": {
        "display_name": "Auth0",
        "authorization_endpoint": "https://{tenant}/authorize",
        "token_endpoint": "https://{tenant}/oauth/token",
        "userinfo_endpoint": "https://{tenant}/userinfo",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
        "tenant_aware": True,
    },
    "keycloak": {
        "display_name": "Keycloak",
        "authorization_endpoint": "https://{tenant}/protocol/openid-connect/auth",
        "token_endpoint": "https://{tenant}/protocol/openid-connect/token",
        "userinfo_endpoint": "https://{tenant}/protocol/openid-connect/userinfo",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
        "tenant_aware": True,
    },
    "generic": {
        "display_name": "Generic OIDC",
        "authorization_endpoint": "{authorization_endpoint}",
        "token_endpoint": "{token_endpoint}",
        "userinfo_endpoint": "{userinfo_endpoint}",
        "default_scopes": ["openid", "email", "profile"],
        "email_claim": "email",
        "name_claim": "name",
        "tenant_aware": True,
    },
}


def _ensure_dirs():
    for p in (CONFIG_PATH, AUDIT_PATH):
        d = os.path.dirname(p)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def _load_config() -> dict:
    _ensure_dirs()
    if not os.path.exists(CONFIG_PATH):
        return {"providers": {}}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"providers": {}}


def _save_config(cfg: dict) -> None:
    _ensure_dirs()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _audit(event: str, payload: dict) -> None:
    _ensure_dirs()
    rec = {"ts": time.time(), "event": event, **payload}
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _prune_states() -> None:
    now = time.time()
    with _state_lock:
        expired = [k for k, v in _state_store.items() if v.get("expires_at", 0) < now]
        for k in expired:
            _state_store.pop(k, None)


def _resolve_endpoints(name: str, provider_cfg: dict) -> dict:
    preset = PROVIDERS.get(name)
    if not preset:
        raise ValueError(f"unknown provider: {name}")
    tenant = provider_cfg.get("tenant_id")
    if name == "microsoft" and not tenant:
        tenant = preset.get("default_tenant", "organizations")
    resolved = {}
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
        val = provider_cfg.get(key) or preset[key]
        if "{tenant}" in val:
            if not tenant:
                raise ValueError(f"provider {name} requires tenant_id")
            val = val.replace("{tenant}", tenant.strip("/"))
        resolved[key] = val
    resolved["email_claim"] = preset.get("email_claim", "email")
    resolved["name_claim"] = preset.get("name_claim", "name")
    return resolved


def get_providers() -> dict:
    cfg = _load_config()
    out = {}
    for name, preset in PROVIDERS.items():
        pcfg = cfg.get("providers", {}).get(name, {})
        configured = bool(pcfg.get("client_id") and pcfg.get("client_secret"))
        out[name] = {
            "display_name": preset["display_name"],
            "configured": configured,
            "tenant_aware": bool(preset.get("tenant_aware")),
            "tenant_id": pcfg.get("tenant_id"),
            "scopes": pcfg.get("scopes") or preset["default_scopes"],
            "has_role_map": bool(pcfg.get("role_map")),
        }
    return out


def configure_provider(name: str, client_id: str, client_secret: str,
                       tenant_id: Optional[str] = None,
                       scopes: Optional[list] = None,
                       role_map: Optional[dict] = None,
                       endpoints: Optional[dict] = None) -> dict:
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider: {name}")
    if not client_id or not client_secret:
        raise ValueError("client_id and client_secret required")
    with _cfg_lock:
        cfg = _load_config()
        cfg.setdefault("providers", {})
        entry = {
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id,
            "scopes": scopes,
            "role_map": role_map or {},
        }
        if endpoints and name == "generic":
            for k in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
                if endpoints.get(k):
                    entry[k] = endpoints[k]
        cfg["providers"][name] = entry
        _save_config(cfg)
    _audit("configure_provider", {"provider": name})
    return {"ok": True, "provider": name, "configured": True}


def remove_provider(name: str) -> dict:
    with _cfg_lock:
        cfg = _load_config()
        if name in cfg.get("providers", {}):
            cfg["providers"].pop(name, None)
            _save_config(cfg)
            _audit("remove_provider", {"provider": name})
            return {"ok": True, "provider": name, "removed": True}
    return {"ok": False, "provider": name, "removed": False, "error": "not configured"}


def revoke_provider(name: str) -> dict:
    res = remove_provider(name)
    _audit("revoke_provider", {"provider": name, "result": res})
    return res


def start_auth_flow(provider: str, redirect_uri: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if not redirect_uri:
        raise ValueError("redirect_uri required")
    _prune_states()
    cfg = _load_config()
    pcfg = cfg.get("providers", {}).get(provider)
    if not pcfg or not pcfg.get("client_id"):
        raise ValueError(f"provider {provider} not configured")
    endpoints = _resolve_endpoints(provider, pcfg)
    preset = PROVIDERS[provider]
    scopes = pcfg.get("scopes") or preset["default_scopes"]

    state = _b64url(secrets.token_bytes(32))
    nonce = _b64url(secrets.token_bytes(16))
    code_verifier = _b64url(secrets.token_bytes(64))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())

    with _state_lock:
        _state_store[state] = {
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "provider": provider,
            "nonce": nonce,
            "expires_at": time.time() + STATE_TTL,
        }

    params = {
        "response_type": "code",
        "client_id": pcfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = endpoints["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
    _audit("start_auth_flow", {"provider": provider, "state": state[:8] + "..."})
    return {"auth_url": auth_url, "state": state, "expires_in": STATE_TTL}


def _http_post(url: str, data: dict, headers: Optional[dict] = None) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    hdrs = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "ankavm-Hypervisor/2.7.0",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"token endpoint HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"token endpoint unreachable: {e.reason}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        parsed = dict(urllib.parse.parse_qsl(raw))
        if not parsed:
            raise RuntimeError("token endpoint returned non-JSON, non-form response")
        return parsed


def _http_get(url: str, access_token: str) -> dict:
    hdrs = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": "ankavm-Hypervisor/2.7.0",
    }
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"userinfo endpoint HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"userinfo endpoint unreachable: {e.reason}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("userinfo endpoint returned invalid JSON")


def _token_exchange(provider_cfg: dict, endpoints: dict, code: str,
                    code_verifier: str, redirect_uri: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider_cfg["client_id"],
        "client_secret": provider_cfg["client_secret"],
        "code_verifier": code_verifier,
    }
    tok = _http_post(endpoints["token_endpoint"], data)
    if "error" in tok:
        raise RuntimeError(f"token exchange failed: {tok.get('error')}: {tok.get('error_description', '')}")
    if "access_token" not in tok:
        raise RuntimeError("token exchange response missing access_token")
    return tok


def _get_userinfo(endpoints: dict, access_token: str) -> dict:
    info = _http_get(endpoints["userinfo_endpoint"], access_token)
    if not isinstance(info, dict):
        raise RuntimeError("userinfo response not a JSON object")
    return info


def map_email_to_role(email: str, role_map: dict, default: str = "vm-user") -> str:
    if not email or not role_map:
        return default
    email_l = email.lower().strip()
    if email_l in {k.lower() for k in role_map.keys()}:
        for k, v in role_map.items():
            if k.lower() == email_l:
                return v
    domain = email_l.split("@", 1)[1] if "@" in email_l else ""
    for k, v in role_map.items():
        if k.startswith("@") and k[1:].lower() == domain:
            return v
        if k.startswith("*@") and k[2:].lower() == domain:
            return v
    return default


def handle_callback(provider: str, code: str, state: str, base_url: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if not code or not state:
        raise ValueError("code and state required")
    _prune_states()
    with _state_lock:
        st = _state_store.pop(state, None)
    if not st:
        raise RuntimeError("invalid or expired state")
    if st["expires_at"] < time.time():
        raise RuntimeError("state expired (>10 min)")
    if st["provider"] != provider:
        raise RuntimeError("state/provider mismatch")

    cfg = _load_config()
    pcfg = cfg.get("providers", {}).get(provider)
    if not pcfg:
        raise RuntimeError(f"provider {provider} not configured")
    endpoints = _resolve_endpoints(provider, pcfg)

    tok = _token_exchange(pcfg, endpoints, code, st["code_verifier"], st["redirect_uri"])
    access_token = tok["access_token"]
    info = _get_userinfo(endpoints, access_token)

    email_claim = endpoints["email_claim"]
    name_claim = endpoints["name_claim"]
    email = info.get(email_claim) or info.get("preferred_username") or info.get("upn")

    if not email and provider == "github":
        try:
            emails = _http_get("https://api.github.com/user/emails", access_token)
            if isinstance(emails, list):
                for e in emails:
                    if e.get("primary") and e.get("verified"):
                        email = e.get("email")
                        break
        except Exception:
            pass

    if not email:
        raise RuntimeError(f"userinfo missing email claim '{email_claim}'")

    name = info.get(name_claim) or info.get("login") or email
    role_map = pcfg.get("role_map") or {}
    role = map_email_to_role(email, role_map)
    ankavm_user_id = "oauth2:" + provider + ":" + hashlib.sha256(email.lower().encode()).hexdigest()[:16]

    result = {
        "email": email,
        "name": name,
        "role": role,
        "ankavm_user_id": ankavm_user_id,
        "provider": provider,
        "raw_userinfo": info,
    }
    _audit("handle_callback", {
        "provider": provider,
        "email": email,
        "role": role,
        "ankavm_user_id": ankavm_user_id,
    })
    return result


def get_audit(limit: int = 100) -> list:
    if not os.path.exists(AUDIT_PATH):
        return []
    try:
        with open(AUDIT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def get_endpoint_code() -> str:
    return r'''
# ===== OAuth 2.0 SSO endpoints (paste into app.py) =====
from flask import request, jsonify, redirect
from . import oauth2_sso

def _require_admin():
    # Replace with your existing admin auth check
    user = getattr(request, "current_user", None)
    if not user or user.get("role") != "admin":
        return jsonify({"error": "admin required"}), 403
    return None

@app.route("/api/auth/oauth2/providers", methods=["GET"])
def oauth2_list_providers():
    return jsonify(oauth2_sso.get_providers())

@app.route("/api/auth/oauth2/providers/<name>", methods=["POST"])
def oauth2_configure_provider(name):
    err = _require_admin()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    try:
        res = oauth2_sso.configure_provider(
            name=name,
            client_id=body.get("client_id", ""),
            client_secret=body.get("client_secret", ""),
            tenant_id=body.get("tenant_id"),
            scopes=body.get("scopes"),
            role_map=body.get("role_map"),
            endpoints=body.get("endpoints"),
        )
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/oauth2/providers/<name>", methods=["DELETE"])
def oauth2_remove_provider(name):
    err = _require_admin()
    if err:
        return err
    return jsonify(oauth2_sso.remove_provider(name))

@app.route("/api/auth/oauth2/<provider>/start", methods=["GET"])
def oauth2_start(provider):
    redirect_uri = request.args.get("redirect") or (request.host_url.rstrip("/") + f"/api/auth/oauth2/{provider}/callback")
    try:
        res = oauth2_sso.start_auth_flow(provider, redirect_uri)
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/oauth2/<provider>/callback", methods=["GET"])
def oauth2_callback(provider):
    code = request.args.get("code")
    state = request.args.get("state")
    err = request.args.get("error")
    if err:
        return jsonify({"error": err, "description": request.args.get("error_description")}), 400
    try:
        res = oauth2_sso.handle_callback(provider, code, state, request.host_url.rstrip("/"))
        # Issue ankavm JWT (use your existing jwt_manager)
        # token = jwt_manager.issue(res["ankavm_user_id"], res["role"], email=res["email"])
        # return redirect(f"/dashboard?token={token}")
        return jsonify(res)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 401

@app.route("/api/auth/oauth2/audit", methods=["GET"])
def oauth2_audit():
    err = _require_admin()
    if err:
        return err
    limit = int(request.args.get("limit", 100))
    return jsonify(oauth2_sso.get_audit(limit))
# ===== end OAuth 2.0 SSO endpoints =====
'''






