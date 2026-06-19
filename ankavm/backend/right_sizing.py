"""
ankavm Right-Sizing Advisor + Capacity Planning + Forecasting
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GeÃ§miÅŸ perf_history verisinden VM kaynaklarÄ±nÄ± analiz et:
  - Over-provisioned? (CPU/RAM az kullanÄ±yorsa downsize Ã¶ner)
  - Under-provisioned? (CPU/RAM hep dolu â†’ upsize Ã¶ner)
  - Cluster kapasite tahmini (linear regression)

API:
    analyze_vm(vm_id, period='30d') -> dict
    list_recommendations(min_savings_pct=10) -> list
    forecast_capacity(metric='disk', period_days=90) -> dict
"""

import logging, time, statistics
from pathlib import Path

log = logging.getLogger("right_sizing")

try:
    import perf_history
except ImportError:
    perf_history = None


def analyze_vm(vm_id: str, period: str = "30d") -> dict:
    """VM'in geÃ§miÅŸ kullanÄ±mÄ±na gÃ¶re right-size Ã¶nerisi."""
    if not perf_history:
        return {"error": "perf_history modÃ¼lÃ¼ yok"}

    try:
        rows = perf_history.get_vm_history(vm_id, period)
    except Exception as e:
        return {"error": str(e)}

    if not rows or len(rows) < 10:
        return {"vm_id": vm_id, "recommendation": None,
                "reason": "Yetersiz veri (min 10 Ã¶rnek gerekli)"}

    cpu_vals  = [r.get("cpu_pct", 0) or 0 for r in rows]
    mem_vals  = [r.get("mem_pct", 0) or 0 for r in rows]

    cpu_avg  = sum(cpu_vals) / len(cpu_vals)
    cpu_p95  = sorted(cpu_vals)[int(len(cpu_vals) * 0.95)]
    cpu_max  = max(cpu_vals)
    mem_avg  = sum(mem_vals) / len(mem_vals)
    mem_p95  = sorted(mem_vals)[int(len(mem_vals) * 0.95)]
    mem_max  = max(mem_vals)

    recs = []
    # CPU Ã¶nerileri
    if cpu_p95 < 25 and cpu_avg < 15:
        recs.append({
            "resource": "vcpu",
            "action":   "decrease",
            "current_usage": {"avg": round(cpu_avg, 1), "p95": round(cpu_p95, 1)},
            "suggestion":    "vCPU sayÄ±sÄ±nÄ± yarÄ±ya indirmeyi dÃ¼ÅŸÃ¼n",
            "savings_pct":   50,
        })
    elif cpu_p95 > 85 and cpu_avg > 60:
        recs.append({
            "resource": "vcpu",
            "action":   "increase",
            "current_usage": {"avg": round(cpu_avg, 1), "p95": round(cpu_p95, 1)},
            "suggestion":    "vCPU sayÄ±sÄ±nÄ± arttÄ±r â€” sÃ¼rekli yÃ¼ksek yÃ¼k",
            "savings_pct":   0,
        })

    # RAM Ã¶nerileri
    if mem_p95 < 35 and mem_avg < 25:
        recs.append({
            "resource": "memory",
            "action":   "decrease",
            "current_usage": {"avg": round(mem_avg, 1), "p95": round(mem_p95, 1)},
            "suggestion":    "RAM'i %50 azaltabilirsin",
            "savings_pct":   50,
        })
    elif mem_p95 > 90:
        recs.append({
            "resource": "memory",
            "action":   "increase",
            "current_usage": {"avg": round(mem_avg, 1), "p95": round(mem_p95, 1)},
            "suggestion":    "RAM'i %50 arttÄ±r â€” swap riski yÃ¼ksek",
            "savings_pct":   0,
        })

    return {
        "vm_id":     vm_id,
        "period":    period,
        "samples":   len(rows),
        "stats": {
            "cpu_avg": round(cpu_avg, 1), "cpu_p95": round(cpu_p95, 1), "cpu_max": round(cpu_max, 1),
            "mem_avg": round(mem_avg, 1), "mem_p95": round(mem_p95, 1), "mem_max": round(mem_max, 1),
        },
        "recommendations": recs,
    }


def list_recommendations(min_savings_pct: int = 10) -> list:
    """TÃ¼m VM'leri analiz et, Ã¶neri olanlarÄ± dÃ¶ndÃ¼r."""
    if not perf_history:
        return []
    try:
        import subprocess
        r = subprocess.run(["virsh", "list", "--all", "--uuid"],
                           capture_output=True, text=True, timeout=10)
        vm_ids = [v.strip() for v in r.stdout.splitlines() if v.strip()]
    except Exception:
        vm_ids = []

    out = []
    for vmid in vm_ids:
        an = analyze_vm(vmid, "30d")
        recs = an.get("recommendations", [])
        if any(r.get("savings_pct", 0) >= min_savings_pct or r.get("action") == "increase"
                for r in recs):
            out.append(an)
    return out


def _linear_regression(xs, ys):
    """Basit least squares y = ax + b."""
    n = len(xs)
    if n < 2:
        return 0, ys[0] if ys else 0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0, my
    a = num / den
    b = my - a * mx
    return a, b


def forecast_capacity(metric: str = "disk", period_days: int = 90) -> dict:
    """Trend bazlÄ± kapasite tahmini. metric: disk | cpu | ram"""
    if not perf_history:
        return {"error": "perf_history yok"}
    try:
        rows = perf_history.get_system_history(f"{period_days}d")
    except Exception as e:
        return {"error": str(e)}

    if not rows or len(rows) < 10:
        return {"error": "Yetersiz veri"}

    if metric == "cpu":
        ys = [r.get("cpu_pct", 0) or 0 for r in rows]
    elif metric == "ram":
        ys = [r.get("mem_pct", 0) or 0 for r in rows]
    elif metric == "disk":
        ys = [(r.get("mem_used_mb", 0) or 0) / max(r.get("mem_total_mb", 1), 1) * 100
              for r in rows]
    else:
        return {"error": "Bilinmeyen metric"}

    xs = list(range(len(ys)))
    slope, intercept = _linear_regression(xs, ys)

    # Forecast: ne zaman %100'e ulaÅŸÄ±r?
    days_to_full = None
    if slope > 0:
        steps_to_100 = (100 - ys[-1]) / slope
        sample_interval_minutes = (rows[-1].get("ts", 0) - rows[0].get("ts", 0)) / max(len(rows) - 1, 1) / 60
        days_to_full = int(steps_to_100 * sample_interval_minutes / 60 / 24)

    # 30 gÃ¼n sonrasÄ± tahmin
    forecast_30d = intercept + slope * (len(ys) + 30 * 24 * 60)  # rough
    return {
        "metric":              metric,
        "period_days":         period_days,
        "current_value":       round(ys[-1], 1),
        "average":             round(sum(ys) / len(ys), 1),
        "trend":               "up" if slope > 0.01 else "down" if slope < -0.01 else "stable",
        "slope_per_sample":    round(slope, 4),
        "forecast_30d_pct":    round(min(max(forecast_30d, 0), 200), 1),
        "days_until_full":     days_to_full,
        "samples":             len(ys),
    }






