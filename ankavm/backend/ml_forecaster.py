"""
ml_forecaster.py — Heatmap + Forecasting (stdlib only, no numpy/scipy)
ankavm v2.5.8 Observability

Features:
  - forecast_resource(metric, horizon_days) — linear trend + moving avg
  - get_heatmap(metric, period) — hour×day matrix
  - capacity_forecast() — "X days until disk/ram full"

Uses perf_history (_safe_import) for data.  Graceful empty if no data.
"""

from __future__ import annotations
import logging
import time
import importlib
from typing import Optional

log = logging.getLogger("ml_forecaster")

# Lazy import of perf_history (same pattern as app.py _safe_import)
_perf_history = None


def _get_perf():
    global _perf_history
    if _perf_history is None:
        try:
            _perf_history = importlib.import_module("perf_history")
        except Exception as e:
            log.debug("perf_history not available: %s", e)
    return _perf_history


# ── Math helpers (stdlib only) ────────────────────────────────────────────────

def _linreg(xs: list, ys: list):
    """Simple linear regression. Returns (slope, intercept)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    sum_x  = sum(xs)
    sum_y  = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom  = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return 0.0, sum_y / n
    slope     = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def _moving_avg(values: list, window: int = 5) -> float:
    if not values:
        return 0.0
    tail = values[-window:]
    return sum(tail) / len(tail)


def _r_squared(xs: list, ys: list, slope: float, intercept: float) -> float:
    """Coefficient of determination R²."""
    if len(ys) < 2:
        return 0.0
    y_mean = sum(ys) / len(ys)
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot == 0:
        return 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    return max(0.0, 1.0 - ss_res / ss_tot)


# ── Metric extraction ─────────────────────────────────────────────────────────

_METRIC_COLUMNS = {
    "cpu":  "cpu_pct",
    "ram":  "mem_pct",
    "disk": "disk_pct",
}

_METRIC_USED_COLUMNS = {
    "disk": ("disk_used_gb", "disk_total_gb"),
    "ram":  ("mem_used_mb",  "mem_total_mb"),
}


def _fetch_history(period: str = "30d") -> list:
    ph = _get_perf()
    if ph is None:
        return []
    try:
        return ph.get_system_history(period)
    except Exception as e:
        log.debug("perf_history fetch fail: %s", e)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def forecast_resource(metric: str = "cpu", horizon_days: int = 30) -> dict:
    """
    Linear trend forecast for cpu / ram / disk.
    Returns {metric, horizon_days, current, predicted, trend, confidence, points_used}.
    """
    if metric not in _METRIC_COLUMNS:
        return {"error": f"unknown metric: {metric}. Use cpu, ram, or disk."}

    col     = _METRIC_COLUMNS[metric]
    rows    = _fetch_history("30d")
    horizon = max(1, min(int(horizon_days), 365))

    if not rows:
        return {
            "metric":       metric,
            "horizon_days": horizon,
            "current":      None,
            "predicted":    None,
            "trend":        "unknown",
            "confidence":   0.0,
            "points_used":  0,
        }

    # Extract (timestamp, value) pairs
    pairs = [(r["ts"], r.get(col)) for r in rows if r.get(col) is not None]
    if not pairs:
        return {
            "metric":       metric,
            "horizon_days": horizon,
            "current":      None,
            "predicted":    None,
            "trend":        "unknown",
            "confidence":   0.0,
            "points_used":  0,
        }

    # Normalise timestamps to days from first point
    t0     = pairs[0][0]
    xs     = [(ts - t0) / 86400.0 for ts, _ in pairs]
    ys     = [float(v) for _, v in pairs]
    slope, intercept = _linreg(xs, ys)
    r2     = _r_squared(xs, ys, slope, intercept)

    future_x  = xs[-1] + horizon
    predicted = round(slope * future_x + intercept, 2)
    predicted = max(0.0, min(predicted, 100.0))

    current   = round(_moving_avg(ys, 5), 2)

    if slope > 0.1:
        trend = "increasing"
    elif slope < -0.1:
        trend = "decreasing"
    else:
        trend = "stable"

    return {
        "metric":       metric,
        "horizon_days": horizon,
        "current":      current,
        "predicted":    predicted,
        "trend":        trend,
        "confidence":   round(r2, 4),
        "points_used":  len(ys),
    }


def get_heatmap(metric: str = "cpu", period: str = "24h") -> dict:
    """
    Build an hour×day heatmap matrix.
    Returns {metric, period, matrix: [[avg_val per hour for each day], ...],
             hours: [0..23], days: ["Mon","Tue",...]}
    """
    if metric not in _METRIC_COLUMNS:
        return {"error": f"unknown metric: {metric}"}

    col  = _METRIC_COLUMNS[metric]
    rows = _fetch_history(period if period in ("24h", "7d", "30d") else "24h")

    # matrix[day_of_week][hour] = list of values
    import time as _time
    buckets: list = [[[] for _ in range(24)] for _ in range(7)]
    for r in rows:
        val = r.get(col)
        if val is None:
            continue
        try:
            t_struct = _time.localtime(r["ts"])
            dow  = t_struct.tm_wday   # 0=Mon
            hour = t_struct.tm_hour
            buckets[dow][hour].append(float(val))
        except Exception:
            pass

    matrix = []
    for dow in range(7):
        row = []
        for hour in range(24):
            vals = buckets[dow][hour]
            row.append(round(sum(vals) / len(vals), 2) if vals else None)
        matrix.append(row)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "metric": metric,
        "period": period,
        "hours":  list(range(24)),
        "days":   days,
        "matrix": matrix,
    }


def capacity_forecast() -> dict:
    """
    Estimate "days until disk/ram full" based on growth rate.
    Returns {disk: {days_until_full, current_pct, growth_pct_per_day},
             ram:  {...}}.
    """
    rows = _fetch_history("30d")

    def _forecast_fill(col_pct: str) -> dict:
        pairs = [(r["ts"], r.get(col_pct)) for r in rows if r.get(col_pct) is not None]
        if len(pairs) < 2:
            return {"days_until_full": None, "current_pct": None, "growth_pct_per_day": None}
        t0 = pairs[0][0]
        xs = [(ts - t0) / 86400.0 for ts, _ in pairs]
        ys = [float(v) for _, v in pairs]
        slope, intercept = _linreg(xs, ys)
        current = round(_moving_avg(ys, 5), 2)
        if slope <= 0:
            days_until_full = None
        else:
            remaining = 100.0 - current
            days_until_full = round(remaining / slope, 1) if slope > 0 else None
        return {
            "days_until_full":    days_until_full,
            "current_pct":        current,
            "growth_pct_per_day": round(slope, 4),
        }

    return {
        "disk": _forecast_fill("disk_pct"),
        "ram":  _forecast_fill("mem_pct"),
    }






