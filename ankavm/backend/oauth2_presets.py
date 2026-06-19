"""ankavm OAuth2 provider presets â€” Keycloak, Authentik, Okta, etc.

One-click presets fill the discovery URL, scopes, and claim mappings for
common identity providers. The operator then just plugs in the client_id
and client_secret. Composes with sso_manager which handles the actual
OIDC flow.
"""
from __future__ import annotations

PRESETS = {
    "keycloak": {
        "label": "Keycloak (self-hosted)",
        "discovery_url_template": "https://{base}/realms/{realm}/.well-known/openid-configuration",
        "params": [
            {"name": "base", "label": "Keycloak base URL",
             "placeholder": "keycloak.corp.example.com"},
            {"name": "realm", "label": "Realm name", "placeholder": "ankavm"},
        ],
        "scopes": ["openid", "profile", "email", "roles"],
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_roles": "realm_access.roles",
    },
    "authentik": {
        "label": "Authentik",
        "discovery_url_template": "https://{base}/application/o/{slug}/.well-known/openid-configuration",
        "params": [
            {"name": "base", "label": "Authentik base URL",
             "placeholder": "authentik.corp.example.com"},
            {"name": "slug", "label": "Application slug",
             "placeholder": "ankavm"},
        ],
        "scopes": ["openid", "profile", "email", "goauthentik.io/api"],
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_roles": "groups",
    },
    "okta": {
        "label": "Okta",
        "discovery_url_template": "https://{base}/oauth2/default/.well-known/openid-configuration",
        "params": [
            {"name": "base", "label": "Okta org URL",
             "placeholder": "corp.okta.com"},
        ],
        "scopes": ["openid", "profile", "email", "groups"],
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_roles": "groups",
    },
    "azure_ad": {
        "label": "Microsoft Entra ID (Azure AD)",
        "discovery_url_template": "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
        "params": [
            {"name": "tenant", "label": "Tenant ID",
             "placeholder": "00000000-0000-0000-0000-000000000000"},
        ],
        "scopes": ["openid", "profile", "email", "User.Read"],
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_roles": "roles",
    },
    "google": {
        "label": "Google Workspace",
        "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
        "params": [],
        "scopes": ["openid", "profile", "email"],
        "claim_username": "email",
        "claim_email": "email",
        "claim_roles": "",
    },
    "gitlab": {
        "label": "GitLab (self-hosted or .com)",
        "discovery_url_template": "https://{base}/.well-known/openid-configuration",
        "params": [
            {"name": "base", "label": "GitLab base URL",
             "placeholder": "gitlab.corp.example.com"},
        ],
        "scopes": ["openid", "profile", "email"],
        "claim_username": "preferred_username",
        "claim_email": "email",
        "claim_roles": "groups",
    },
}


def list_presets() -> list:
    return [{"id": k, **v} for k, v in PRESETS.items()]


def get_preset(preset_id: str) -> dict | None:
    return PRESETS.get(preset_id)


def render_discovery_url(preset_id: str, params: dict) -> str | None:
    """Substitute the {placeholder} tokens in a discovery URL template with
    operator-supplied params. Uses a simple iterative replace rather than
    str.format so the function cannot be coaxed into reading attributes."""
    p = PRESETS.get(preset_id)
    if not p:
        return None
    if "discovery_url" in p:
        return p["discovery_url"]
    tpl = p["discovery_url_template"]
    out = tpl
    for k, v in (params or {}).items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        out = out.replace("{" + k + "}", v)
    if "{" in out and "}" in out:
        raise ValueError(f"unfilled placeholders in discovery URL for {preset_id!r}")
    return out






