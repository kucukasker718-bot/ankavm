"""
ankavm Chargeback Engine — Per-Tenant Cost Tracking
─────────────────────────────────────────────────────
İcra anlık (on-demand) — periodic job YOK; sunucuya yük yapmaz.

  - Fiyatlandırma: /var/lib/ankavm/chargeback_config.json
  - Faturalar:    /var/lib/ankavm/invoices/<tenant>/<YYYY-MM>.json
  - Veri kaynağı: tenant_manager.get_tenant_usage()
                  perf_history (varsa) → ortalama CPU yüklemesi
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("chargeback_engine")

_CFG_FILE     = Path("/var/lib/ankavm/chargeback_config.json")
_INVOICE_DIR  = Path("/var/lib/ankavm/invoices")
_lock         = threading.RLock()

# Default fiyatlandırma — operatör override eder
DEFAULT_PRICING = {
    "currency":             "EUR",
    "vcpu_per_hour":        0.01,
    "ram_gb_per_hour":      0.005,
    "disk_gb_per_month":    0.10,
    "ip_per_month":         2.00,
    "snapshot_gb_per_month":0.05,
}


# ── Pricing config ────────────────────────────────────────────────────────────
def _load_cfg() -> dict:
    try:
        if _CFG_FILE.exists():
            cfg = json.loads(_CFG_FILE.read_text(encoding="utf-8"))
            # Eksik anahtarlar default'a düşsün
            out = dict(DEFAULT_PRICING)
            for k, v in cfg.items():
                if k in out:
                    out[k] = v
            return out
    except Exception as e:
        log.warning("chargeback cfg load fail: %s", e)
    return dict(DEFAULT_PRICING)


def _save_cfg(cfg: dict) -> None:
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CFG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _CFG_FILE)
    except Exception as e:
        log.warning("chargeback cfg save fail: %s", e)


def get_pricing() -> dict:
    with _lock:
        return _load_cfg()


def set_pricing(config: dict) -> dict:
    if not isinstance(config, dict):
        return {"ok": False, "error": "geçersiz config"}
    with _lock:
        cur = _load_cfg()
        for k, v in (config or {}).items():
            if k in DEFAULT_PRICING:
                cur[k] = v
        # currency tip kontrolü
        if "currency" in cur:
            cur["currency"] = str(cur["currency"]).upper()
        _save_cfg(cur)
        return {"ok": True, "pricing": cur}


# ── Lazy modules ──────────────────────────────────────────────────────────────
def _tm():
    try:
        import tenant_manager  # type: ignore
        return tenant_manager
    except Exception:
        return None


# ── Hesaplama ─────────────────────────────────────────────────────────────────
_PERIOD_HOURS = {
    "daily":   24,
    "weekly":  24 * 7,
    "monthly": 24 * 30,
    "yearly":  24 * 365,
}


def _hours_in_period(period: str) -> int:
    return _PERIOD_HOURS.get(period, _PERIOD_HOURS["monthly"])


def _month_fraction(period: str) -> float:
    """Aylık ücretler için periyod ne kadar ay tutar."""
    h = _hours_in_period(period)
    return h / (24.0 * 30.0)


def calculate_tenant_cost(tenant_id: str, period: str = "monthly") -> dict:
    """
    Anlık hesap: kullanım × fiyat × süre. Periodic job yok — request-time.
    """
    pricing = get_pricing()
    tm = _tm()
    if not tm:
        return {"breakdown": [], "total": 0.0, "currency": pricing["currency"], "error": "tenant_manager yok"}

    usage = {}
    tenant = {}
    try:
        tenant = tm.get_tenant(tenant_id) or {}
        usage  = tm.get_tenant_usage(tenant_id) or {}
    except Exception as e:
        log.debug("usage fail: %s", e)

    hours       = _hours_in_period(period)
    month_frac  = _month_fraction(period)

    vcpus       = float(usage.get("vcpus_used", 0))
    ram_gb      = float(usage.get("ram_mb_used", 0)) / 1024.0
    disk_gb     = float(usage.get("disk_gb_used", 0))
    ips         = float(usage.get("ips_count", 0))
    snapshot_gb = float(usage.get("snapshot_gb", 0))   # opsiyonel

    line_items = [
        {
            "item":     "vCPU",
            "qty":      vcpus,
            "unit":     "core-hour",
            "hours":    hours,
            "unit_price": pricing["vcpu_per_hour"],
            "amount":   round(vcpus * pricing["vcpu_per_hour"] * hours, 4),
        },
        {
            "item":     "RAM",
            "qty":      ram_gb,
            "unit":     "GB-hour",
            "hours":    hours,
            "unit_price": pricing["ram_gb_per_hour"],
            "amount":   round(ram_gb * pricing["ram_gb_per_hour"] * hours, 4),
        },
        {
            "item":     "Disk",
            "qty":      disk_gb,
            "unit":     "GB-month",
            "months":   round(month_frac, 4),
            "unit_price": pricing["disk_gb_per_month"],
            "amount":   round(disk_gb * pricing["disk_gb_per_month"] * month_frac, 4),
        },
        {
            "item":     "Public IP",
            "qty":      ips,
            "unit":     "IP-month",
            "months":   round(month_frac, 4),
            "unit_price": pricing["ip_per_month"],
            "amount":   round(ips * pricing["ip_per_month"] * month_frac, 4),
        },
        {
            "item":     "Snapshot Storage",
            "qty":      snapshot_gb,
            "unit":     "GB-month",
            "months":   round(month_frac, 4),
            "unit_price": pricing["snapshot_gb_per_month"],
            "amount":   round(snapshot_gb * pricing["snapshot_gb_per_month"] * month_frac, 4),
        },
    ]
    total = round(sum(li["amount"] for li in line_items), 4)
    return {
        "tenant_id":  tenant_id,
        "tenant":     tenant.get("name", ""),
        "period":     period,
        "currency":   pricing["currency"],
        "breakdown":  line_items,
        "total":      total,
        "usage":      usage,
        "calculated_at": int(time.time()),
    }


def generate_invoice(tenant_id: str, year: int, month: int) -> dict:
    """
    Belirli ay için fatura dosyası üret. Re-generate her zaman güncel kullanıma göre.
    """
    try:
        year  = int(year)
        month = int(month)
        if month < 1 or month > 12:
            return {"ok": False, "error": "month 1-12 arası olmalı"}
    except Exception:
        return {"ok": False, "error": "geçersiz tarih"}

    # Aydaki saat sayısı
    days_in_month = monthrange(year, month)[1]
    hours = days_in_month * 24

    pricing = get_pricing()
    tm = _tm()
    tenant = {}
    usage  = {}
    if tm:
        try:
            tenant = tm.get_tenant(tenant_id) or {}
            usage  = tm.get_tenant_usage(tenant_id) or {}
        except Exception:
            pass

    vcpus       = float(usage.get("vcpus_used", 0))
    ram_gb      = float(usage.get("ram_mb_used", 0)) / 1024.0
    disk_gb     = float(usage.get("disk_gb_used", 0))
    ips         = float(usage.get("ips_count", 0))
    snapshot_gb = float(usage.get("snapshot_gb", 0))

    line_items = [
        {"item": "vCPU",             "qty": vcpus,       "hours":  hours, "unit_price": pricing["vcpu_per_hour"],         "amount": round(vcpus * pricing["vcpu_per_hour"] * hours, 4)},
        {"item": "RAM (GB)",         "qty": ram_gb,      "hours":  hours, "unit_price": pricing["ram_gb_per_hour"],       "amount": round(ram_gb * pricing["ram_gb_per_hour"] * hours, 4)},
        {"item": "Disk (GB)",        "qty": disk_gb,     "months": 1,     "unit_price": pricing["disk_gb_per_month"],     "amount": round(disk_gb * pricing["disk_gb_per_month"], 4)},
        {"item": "Public IP",        "qty": ips,         "months": 1,     "unit_price": pricing["ip_per_month"],          "amount": round(ips * pricing["ip_per_month"], 4)},
        {"item": "Snapshot (GB)",    "qty": snapshot_gb, "months": 1,     "unit_price": pricing["snapshot_gb_per_month"], "amount": round(snapshot_gb * pricing["snapshot_gb_per_month"], 4)},
    ]
    subtotal = round(sum(li["amount"] for li in line_items), 4)
    invoice = {
        "tenant_id":   tenant_id,
        "tenant":      tenant.get("name", ""),
        "period":      f"{year:04d}-{month:02d}",
        "issued_at":   int(time.time()),
        "issued_iso":  datetime.now(timezone.utc).isoformat(),
        "currency":    pricing["currency"],
        "line_items":  line_items,
        "subtotal":    subtotal,
        "tax_rate":    0.0,
        "tax":         0.0,
        "total":       subtotal,
        "invoice_no":  f"OXW-{year:04d}{month:02d}-{tenant_id[:8]}",
    }
    # Persist
    try:
        out_dir = _INVOICE_DIR / tenant_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{year:04d}-{month:02d}.json"
        tmp  = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(invoice, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        invoice["path"] = str(path)
    except Exception as e:
        log.warning("invoice save fail: %s", e)
    return invoice


def get_invoice(tenant_id: str, year: int, month: int) -> Optional[dict]:
    try:
        path = _INVOICE_DIR / tenant_id / f"{int(year):04d}-{int(month):02d}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def list_tenant_invoices(tenant_id: str) -> list:
    out = []
    try:
        d = _INVOICE_DIR / tenant_id
        if d.exists():
            for f in sorted(d.glob("*.json")):
                try:
                    out.append({"period": f.stem, "path": str(f)})
                except Exception:
                    pass
    except Exception:
        pass
    return out


def get_all_tenants_billing(period: str = "monthly") -> list:
    """Tüm tenant'lar için anlık maliyet özeti."""
    tm = _tm()
    out = []
    if not tm:
        return out
    try:
        for t in tm.list_tenants():
            tid = t.get("id")
            if not tid:
                continue
            try:
                cost = calculate_tenant_cost(tid, period)
                out.append({
                    "tenant_id": tid,
                    "tenant":    t.get("name", ""),
                    "total":     cost.get("total", 0.0),
                    "currency":  cost.get("currency", ""),
                    "period":    period,
                })
            except Exception as e:
                log.debug("billing calc fail %s: %s", tid, e)
    except Exception:
        pass
    return out






