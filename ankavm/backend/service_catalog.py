"""
ankavm Service Catalog — Self-Service VM Templates
─────────────────────────────────────────────────────
Operatörün kataloğa eklediği "ready-to-deploy" VM şablonları.

  - Persistent: /var/lib/ankavm/service_catalog.json (atomic write)
  - Built-in default catalog: Ubuntu, Debian, Windows Server, WordPress,
    GitLab CE, Docker Host
  - deploy_from_catalog → self_service_portal.request_vm_create() çağırır
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("service_catalog")

_FILE = Path("/var/lib/ankavm/service_catalog.json")
_lock = threading.RLock()

# ── Built-in default items ────────────────────────────────────────────────────
DEFAULT_CATALOG = [
    {
        "id":               "builtin-ubuntu-24",
        "name":             "Ubuntu 24.04 LTS",
        "description":      "Canonical Ubuntu Server 24.04 LTS (Noble) — cloud-init enabled",
        "category":         "linux",
        "icon":             "ubuntu",
        "template_id":      "ubuntu-24.04",
        "default_vcpus":    2,
        "default_ram_mb":   2048,
        "default_disk_gb":  20,
        "allowed_tenants":  [],
        "price_per_month":  5.00,
        "builtin":          True,
    },
    {
        "id":               "builtin-debian-12",
        "name":             "Debian 12",
        "description":      "Debian 12 (Bookworm) — minimal cloud image",
        "category":         "linux",
        "icon":             "debian",
        "template_id":      "debian-12",
        "default_vcpus":    1,
        "default_ram_mb":   1024,
        "default_disk_gb":  15,
        "allowed_tenants":  [],
        "price_per_month":  4.00,
        "builtin":          True,
    },
    {
        "id":               "builtin-winsrv-2022",
        "name":             "Windows Server 2022",
        "description":      "Windows Server 2022 — Standard Edition (BYOL veya değerlendirme)",
        "category":         "windows",
        "icon":             "windows",
        "template_id":      "winsrv-2022",
        "default_vcpus":    4,
        "default_ram_mb":   8192,
        "default_disk_gb":  60,
        "allowed_tenants":  [],
        "price_per_month":  25.00,
        "builtin":          True,
    },
    {
        "id":               "builtin-wordpress",
        "name":             "WordPress Stack",
        "description":      "Ubuntu + Nginx + PHP-FPM + MySQL + WordPress",
        "category":         "app",
        "icon":             "wordpress",
        "template_id":      "wordpress-stack",
        "default_vcpus":    2,
        "default_ram_mb":   2048,
        "default_disk_gb":  30,
        "allowed_tenants":  [],
        "price_per_month":  10.00,
        "builtin":          True,
    },
    {
        "id":               "builtin-gitlab",
        "name":             "GitLab CE",
        "description":      "GitLab Community Edition — DevOps platformu",
        "category":         "devops",
        "icon":             "gitlab",
        "template_id":      "gitlab-ce",
        "default_vcpus":    4,
        "default_ram_mb":   8192,
        "default_disk_gb":  60,
        "allowed_tenants":  [],
        "price_per_month":  20.00,
        "builtin":          True,
    },
    {
        "id":               "builtin-docker-host",
        "name":             "Docker Host",
        "description":      "Ubuntu + Docker CE + docker-compose — hazır container runtime",
        "category":         "container",
        "icon":             "docker",
        "template_id":      "docker-host",
        "default_vcpus":    2,
        "default_ram_mb":   4096,
        "default_disk_gb":  40,
        "allowed_tenants":  [],
        "price_per_month":  8.00,
        "builtin":          True,
    },
]


# ── Persistence ──────────────────────────────────────────────────────────────
def _load() -> list:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as e:
        log.warning("catalog load fail: %s", e)
    return []


def _save(items: list) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _FILE)
    except Exception as e:
        log.warning("catalog save fail: %s", e)


def _all_items() -> list:
    """Built-in + persistent (custom) items birleşik."""
    persistent = _load()
    persistent_ids = {i.get("id") for i in persistent}
    out = list(persistent)
    for b in DEFAULT_CATALOG:
        if b["id"] not in persistent_ids:
            out.append(b)
    return out


# ── Public API ───────────────────────────────────────────────────────────────
def list_catalog(tenant_id: Optional[str] = None) -> list:
    """allowed_tenants boş → herkese açık; dolu → sadece listedeki tenant'lara görünür."""
    items = _all_items()
    if not tenant_id:
        return items
    out = []
    for it in items:
        allowed = it.get("allowed_tenants", []) or []
        if not allowed or tenant_id in allowed:
            out.append(it)
    return out


def get_catalog_item(catalog_id: str) -> Optional[dict]:
    for it in _all_items():
        if it.get("id") == catalog_id:
            return it
    return None


def add_catalog_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {"ok": False, "error": "geçersiz item"}
    name = (item.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name zorunlu"}
    new_item = {
        "id":               item.get("id") or f"custom-{uuid.uuid4()}",
        "name":             name,
        "description":      str(item.get("description", "")),
        "category":         str(item.get("category", "custom")),
        "icon":             str(item.get("icon", "cube")),
        "template_id":      str(item.get("template_id", "")),
        "default_vcpus":    int(item.get("default_vcpus", 1) or 1),
        "default_ram_mb":   int(item.get("default_ram_mb", 1024) or 1024),
        "default_disk_gb":  int(item.get("default_disk_gb", 20) or 20),
        "allowed_tenants":  list(item.get("allowed_tenants", []) or []),
        "price_per_month":  float(item.get("price_per_month", 0.0) or 0.0),
        "builtin":          False,
        "created_at":       int(time.time()),
    }
    with _lock:
        items = _load()
        # Aynı id varsa güncelle
        items = [i for i in items if i.get("id") != new_item["id"]]
        items.append(new_item)
        _save(items)
    return {"ok": True, "item": new_item}


def delete_catalog_item(catalog_id: str) -> dict:
    # builtin silinmez — sadece "gizle" mantığı için ayrı bir mekanizma gerekir
    if any(b["id"] == catalog_id for b in DEFAULT_CATALOG):
        return {"ok": False, "error": "built-in kataloğun silinmesi engellendi"}
    with _lock:
        items = _load()
        new_items = [i for i in items if i.get("id") != catalog_id]
        if len(new_items) == len(items):
            return {"ok": False, "error": "katalog bulunamadı"}
        _save(new_items)
    return {"ok": True, "id": catalog_id}


def deploy_from_catalog(username: str, catalog_id: str, vm_name: str) -> dict:
    """self_service_portal aracılığıyla VM oluşturur — quota + ownership otomatik."""
    item = get_catalog_item(catalog_id)
    if not item:
        return {"ok": False, "error": "katalog bulunamadı"}
    vm_name = (vm_name or "").strip()
    if not vm_name:
        return {"ok": False, "error": "vm_name zorunlu"}

    # Tenant kısıtı (varsa)
    allowed = item.get("allowed_tenants", []) or []
    if allowed:
        try:
            import tenant_manager  # type: ignore
            tid = tenant_manager.get_user_tenant(username)
            if tid not in allowed:
                return {"ok": False, "error": "bu katalog tenant'ınıza atanmamış"}
        except Exception:
            pass

    try:
        import self_service_portal  # type: ignore
    except Exception:
        return {"ok": False, "error": "self_service_portal yok"}

    return self_service_portal.request_vm_create(
        username=username,
        name=vm_name,
        vcpus=int(item.get("default_vcpus", 1)),
        ram_mb=int(item.get("default_ram_mb", 1024)),
        disk_gb=int(item.get("default_disk_gb", 20)),
        template_id=item.get("template_id") or None,
    )






