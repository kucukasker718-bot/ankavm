"""
ankavm Green Mode - AI-driven Power Optimization
================================================
Datacenter electricity savings via:
  - Trend analysis on cluster load history
  - VM consolidation during low-load windows
  - Idle node suspension (ACPI S3, IPMI shutdown, Wake-on-LAN)
  - Predictive wake-up before load spikes
  - Policy-based scheduling (e.g., 02:00-06:00 = green window)

State: /var/lib/ankavm/green_mode.json
Audit: /var/log/ankavm/green_mode.jsonl
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import importlib
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any

STATE_PATH = Path("/var/lib/ankavm/green_mode.json")
AUDIT_PATH = Path("/var/log/ankavm/green_mode.jsonl")
PERF_DB_PATH = Path("/var/lib/ankavm/perf_history.db")

DEFAULT_POLICY: dict[str, Any] = {
    "enabled": False,
    "green_windows": [
        {
            "start": "02:00",
            "end": "06:00",
            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        }
    ],
    "min_load_threshold_pct": 30,
    "consolidation_max_density_pct": 80,
    "wake_lead_minutes": 15,
    "allowed_nodes": [],
    "excluded_vms": [],
    "power_profile_w": {"idle": 150, "peak": 400},
    "co2_factor_kg_per_kwh": 0.4,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:
        try:
            return importlib.import_module(f"ankavm.backend.{name}")
        except Exception:
            return None


def _ensure_dirs() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _load_state() -> dict[str, Any]:
    _ensure_dirs()
    if not STATE_PATH.exists():
        state = {
            "policy": dict(DEFAULT_POLICY),
            "node_states": {},
            "last_consolidation": None,
            "version": "2.6.2",
        }
        _save_state(state)
        return state
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # merge defaults for missing keys
        pol = dict(DEFAULT_POLICY)
        pol.update(data.get("policy") or {})
        data["policy"] = pol
        data.setdefault("node_states", {})
        data.setdefault("last_consolidation", None)
        data.setdefault("version", "2.6.2")
        return data
    except Exception:
        return {
            "policy": dict(DEFAULT_POLICY),
            "node_states": {},
            "last_consolidation": None,
            "version": "2.6.2",
        }


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dirs()
    try:
        tmp = STATE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def _audit(action: str, details: dict[str, Any], kwh_saved: float = 0.0) -> None:
    _ensure_dirs()
    entry = {
        "ts": _now_iso(),
        "action": action,
        "details": details,
        "estimated_kwh_saved": round(float(kwh_saved), 4),
    }
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:
        pass


def _run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "cmd": cmd,
        }
    except FileNotFoundError as e:
        return {"ok": False, "rc": -1, "error": f"binary-missing: {e}", "cmd": cmd}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": -1, "error": "timeout", "cmd": cmd}
    except Exception as e:
        return {"ok": False, "rc": -1, "error": str(e), "cmd": cmd}


def _parse_hhmm(s: str) -> dtime:
    try:
        hh, mm = s.split(":")
        return dtime(int(hh), int(mm))
    except Exception:
        return dtime(0, 0)


def _in_green_window(policy: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or datetime.now()
    day_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
    cur = now.time()
    for win in policy.get("green_windows") or []:
        if day_key not in (win.get("days") or []):
            continue
        s = _parse_hhmm(win.get("start", "00:00"))
        e = _parse_hhmm(win.get("end", "00:00"))
        if s <= e:
            if s <= cur <= e:
                return True
        else:
            # wraps midnight
            if cur >= s or cur <= e:
                return True
    return False


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def get_config() -> dict[str, Any]:
    st = _load_state()
    return {
        "policy": st["policy"],
        "enabled": bool(st["policy"].get("enabled")),
        "in_green_window": _in_green_window(st["policy"]),
        "last_consolidation": st.get("last_consolidation"),
        "node_states": st.get("node_states", {}),
        "version": st.get("version", "2.6.2"),
    }


def set_config(policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(policy, dict):
        return {"ok": False, "error": "policy must be dict"}
    st = _load_state()
    merged = dict(st["policy"])
    for k, v in policy.items():
        if k in DEFAULT_POLICY:
            merged[k] = v
    st["policy"] = merged
    _save_state(st)
    _audit("set_config", {"policy": merged})
    return {"ok": True, "policy": merged}


# ---------------------------------------------------------------------------
# metrics / prediction
# ---------------------------------------------------------------------------

def _read_perf_history(days: int = 7) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cutoff = datetime.utcnow() - timedelta(days=days)
    if PERF_DB_PATH.exists():
        try:
            con = sqlite3.connect(str(PERF_DB_PATH))
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            # try common schema names
            for sql in (
                "SELECT ts, cpu_pct, mem_pct FROM perf_history WHERE ts >= ? ORDER BY ts",
                "SELECT timestamp as ts, cpu as cpu_pct, mem as mem_pct FROM metrics WHERE timestamp >= ? ORDER BY timestamp",
            ):
                try:
                    cur.execute(sql, (cutoff.isoformat(),))
                    for r in cur.fetchall():
                        rows.append(dict(r))
                    if rows:
                        break
                except sqlite3.Error:
                    continue
            con.close()
        except Exception:
            pass
    if rows:
        return rows
    # fallback: event_logger
    ev = _safe_import("event_logger")
    if ev and hasattr(ev, "recent"):
        try:
            for e in ev.recent(limit=days * 24 * 12) or []:
                if "cpu_pct" in e or "cpu" in e:
                    rows.append(
                        {
                            "ts": e.get("ts") or e.get("timestamp"),
                            "cpu_pct": e.get("cpu_pct", e.get("cpu", 0)),
                            "mem_pct": e.get("mem_pct", e.get("mem", 0)),
                        }
                    )
        except Exception:
            pass
    return rows


def predict_load_window(hours_ahead: int = 24) -> list[dict[str, Any]]:
    hours_ahead = max(1, min(int(hours_ahead or 24), 168))
    hist = _read_perf_history(days=7)
    # bucket by hour-of-day
    buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    for r in hist:
        ts = r.get("ts")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", ""))
        except Exception:
            continue
        cpu = float(r.get("cpu_pct") or 0)
        buckets[t.hour].append(cpu)
    hourly_avg = {
        h: (sum(v) / len(v) if v else 35.0) for h, v in buckets.items()
    }
    # linear trend over recent week
    cpus = [float(r.get("cpu_pct") or 0) for r in hist if r.get("cpu_pct") is not None]
    trend = 0.0
    if len(cpus) >= 2:
        first = sum(cpus[: max(1, len(cpus) // 4)]) / max(1, len(cpus) // 4)
        last = sum(cpus[-max(1, len(cpus) // 4):]) / max(1, len(cpus) // 4)
        trend = (last - first) / max(1, len(cpus))
    out: list[dict[str, Any]] = []
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    for i in range(hours_ahead):
        t = now + timedelta(hours=i + 1)
        base = hourly_avg[t.hour]
        forecast = max(0.0, min(100.0, base + trend * i))
        out.append(
            {
                "ts": t.isoformat() + "Z",
                "hour": t.hour,
                "forecast_cpu_pct": round(forecast, 2),
                "is_low_load": forecast < 30.0,
            }
        )
    return out


def analyze_savings_potential() -> dict[str, Any]:
    st = _load_state()
    pol = st["policy"]
    hist = _read_perf_history(days=7)
    if not hist:
        return {
            "ok": True,
            "samples": 0,
            "estimated_kwh_saved_per_week": 0.0,
            "estimated_usd_saved_per_week": 0.0,
            "estimated_co2_kg_saved_per_week": 0.0,
            "note": "no perf history available",
        }
    nodes = _cluster_node_list()
    n_nodes = max(1, len(nodes))
    idle_w = float(pol["power_profile_w"]["idle"])
    peak_w = float(pol["power_profile_w"]["peak"])
    co2 = float(pol["co2_factor_kg_per_kwh"])
    threshold = float(pol["min_load_threshold_pct"])
    # hours below threshold -> consolidate-able
    low_samples = sum(1 for r in hist if float(r.get("cpu_pct") or 0) < threshold)
    total_samples = len(hist)
    low_fraction = low_samples / total_samples
    # assume half of nodes can be suspended during low windows
    suspendable = max(0, (n_nodes // 2))
    hours_per_week = 24 * 7
    low_hours = hours_per_week * low_fraction
    avg_w_saved = (idle_w + (peak_w - idle_w) * 0.2) * suspendable
    kwh_week = (avg_w_saved * low_hours) / 1000.0
    usd_per_kwh = 0.12
    return {
        "ok": True,
        "samples": total_samples,
        "low_load_fraction": round(low_fraction, 3),
        "suspendable_nodes": suspendable,
        "estimated_kwh_saved_per_week": round(kwh_week, 2),
        "estimated_usd_saved_per_week": round(kwh_week * usd_per_kwh, 2),
        "estimated_co2_kg_saved_per_week": round(kwh_week * co2, 2),
    }


def get_green_score() -> dict[str, Any]:
    st = _load_state()
    nodes = _cluster_node_list()
    if not nodes:
        return {"score": 0, "reason": "no nodes"}
    node_states = st.get("node_states", {})
    active = [n for n in nodes if node_states.get(n, {}).get("power_state", "active") == "active"]
    suspended = [n for n in nodes if node_states.get(n, {}).get("power_state") == "suspended"]
    vms_by_node = _vms_per_node()
    total_vms = sum(len(v) for v in vms_by_node.values())
    if active:
        avg_density = total_vms / len(active)
    else:
        avg_density = 0
    consolidation = min(100.0, avg_density * 12.5)  # 8 VMs/node -> 100
    idle_pct = (len(suspended) / len(nodes)) * 100.0
    # peak shaving heuristic: lower current cpu => better
    forecast = predict_load_window(1)
    cur_load = forecast[0]["forecast_cpu_pct"] if forecast else 50.0
    peak_shave = max(0.0, 100.0 - cur_load)
    score = round(0.4 * consolidation + 0.4 * idle_pct + 0.2 * peak_shave, 1)
    return {
        "score": score,
        "consolidation_density": round(consolidation, 1),
        "idle_pct": round(idle_pct, 1),
        "peak_shave": round(peak_shave, 1),
        "active_nodes": len(active),
        "suspended_nodes": len(suspended),
        "total_nodes": len(nodes),
        "total_vms": total_vms,
    }


# ---------------------------------------------------------------------------
# cluster introspection
# ---------------------------------------------------------------------------

def _cluster_node_list() -> list[str]:
    cm = _safe_import("cluster_manager")
    if cm:
        for fn in ("list_nodes", "get_nodes", "nodes"):
            f = getattr(cm, fn, None)
            if callable(f):
                try:
                    res = f()
                    if isinstance(res, list):
                        return [
                            (n if isinstance(n, str) else n.get("name") or n.get("hostname") or "")
                            for n in res
                            if n
                        ]
                except Exception:
                    continue
    st = _load_state()
    return list(st.get("node_states", {}).keys())


def _vms_per_node() -> dict[str, list[dict[str, Any]]]:
    vm = _safe_import("vm_manager")
    by_node: dict[str, list[dict[str, Any]]] = {}
    if vm and hasattr(vm, "list_vms"):
        try:
            for v in vm.list_vms() or []:
                node = v.get("node") or v.get("host") or "local"
                by_node.setdefault(node, []).append(v)
        except Exception:
            pass
    return by_node


def list_node_states() -> list[dict[str, Any]]:
    st = _load_state()
    states = st.get("node_states", {})
    out = []
    for n in _cluster_node_list():
        ent = states.get(n, {})
        out.append(
            {
                "node": n,
                "power_state": ent.get("power_state", "active"),
                "last_change": ent.get("last_change"),
                "method": ent.get("method"),
            }
        )
    return out


def estimate_node_power_w(node: str) -> float:
    st = _load_state()
    pol = st["policy"]
    states = st.get("node_states", {})
    ent = states.get(node, {})
    if ent.get("power_state") == "suspended":
        return 5.0
    profile = ent.get("power_profile_w") or pol.get("power_profile_w") or {}
    idle = float(profile.get("idle", 150))
    peak = float(profile.get("peak", 400))
    # use forecast as proxy
    fc = predict_load_window(1)
    load = (fc[0]["forecast_cpu_pct"] / 100.0) if fc else 0.5
    return round(idle + (peak - idle) * load, 2)


# ---------------------------------------------------------------------------
# consolidation
# ---------------------------------------------------------------------------

def recommend_consolidation() -> dict[str, Any]:
    st = _load_state()
    pol = st["policy"]
    max_density = float(pol["consolidation_max_density_pct"]) / 100.0
    excluded = set(pol.get("excluded_vms") or [])
    allowed = set(pol.get("allowed_nodes") or [])
    nodes = _cluster_node_list()
    if allowed:
        nodes = [n for n in nodes if n in allowed]
    by_node = _vms_per_node()
    # gather all VMs with RAM
    all_vms: list[dict[str, Any]] = []
    for n, vms in by_node.items():
        for v in vms:
            name = v.get("name") or v.get("vmid") or v.get("id")
            if not name or name in excluded:
                continue
            ram = float(v.get("ram_mb") or v.get("mem_mb") or v.get("memory") or 1024)
            all_vms.append({"name": name, "ram_mb": ram, "current_node": n})
    all_vms.sort(key=lambda x: x["ram_mb"], reverse=True)
    # default node capacity 32 GB
    node_capacity = 32 * 1024.0
    cap_used: dict[str, float] = {n: 0.0 for n in nodes}
    placement: dict[str, str] = {}  # vm -> target node
    migrations: list[dict[str, Any]] = []
    for v in all_vms:
        placed = False
        for n in nodes:
            if cap_used[n] + v["ram_mb"] <= node_capacity * max_density:
                placement[v["name"]] = n
                cap_used[n] += v["ram_mb"]
                if n != v["current_node"]:
                    migrations.append(
                        {"vm": v["name"], "from": v["current_node"], "to": n, "ram_mb": v["ram_mb"]}
                    )
                placed = True
                break
        if not placed:
            placement[v["name"]] = v["current_node"]
    suspend_candidates = [n for n in nodes if cap_used[n] == 0.0]
    return {
        "ok": True,
        "migrations": migrations,
        "suspend_candidates": suspend_candidates,
        "placement": placement,
        "node_utilization_mb": cap_used,
        "max_density_pct": pol["consolidation_max_density_pct"],
    }


def enter_green_window(dry_run: bool = True) -> dict[str, Any]:
    st = _load_state()
    pol = st["policy"]
    if not pol.get("enabled") and not dry_run:
        return {"ok": False, "error": "green mode disabled in policy"}
    rec = recommend_consolidation()
    actions: list[dict[str, Any]] = []
    kwh_saved = 0.0
    vm = _safe_import("vm_manager")
    for mig in rec.get("migrations", []):
        act = {"type": "migrate", **mig, "dry_run": dry_run}
        if not dry_run and vm and hasattr(vm, "live_migrate"):
            try:
                res = vm.live_migrate(mig["vm"], mig["to"])
                act["result"] = res
            except Exception as e:
                act["error"] = str(e)
        actions.append(act)
    for node in rec.get("suspend_candidates", []):
        est_w = estimate_node_power_w(node)
        # estimate 4h savings per green window
        kwh_saved += (est_w * 4.0) / 1000.0
        act = {"type": "suspend", "node": node, "dry_run": dry_run, "estimated_w": est_w}
        if not dry_run:
            r = suspend_node(node)
            act["result"] = r
        actions.append(act)
    st["last_consolidation"] = {
        "ts": _now_iso(),
        "dry_run": dry_run,
        "n_migrations": len(rec.get("migrations", [])),
        "n_suspends": len(rec.get("suspend_candidates", [])),
        "estimated_kwh_saved": round(kwh_saved, 3),
    }
    _save_state(st)
    _audit(
        "enter_green_window",
        {"dry_run": dry_run, "actions": actions, "summary": st["last_consolidation"]},
        kwh_saved=kwh_saved,
    )
    return {
        "ok": True,
        "dry_run": dry_run,
        "actions": actions,
        "estimated_kwh_saved": round(kwh_saved, 3),
    }


# ---------------------------------------------------------------------------
# power ops
# ---------------------------------------------------------------------------

def _node_meta(node: str) -> dict[str, Any]:
    st = _load_state()
    return st.get("node_states", {}).get(node, {}) or {}


def _update_node_state(node: str, **kwargs) -> None:
    st = _load_state()
    states = st.setdefault("node_states", {})
    ent = states.setdefault(node, {})
    ent.update(kwargs)
    ent["last_change"] = _now_iso()
    _save_state(st)


def wake_node(node: str, method: str = "wol") -> dict[str, Any]:
    if not node:
        return {"ok": False, "error": "node required"}
    meta = _node_meta(node)
    res: dict[str, Any]
    try:
        if method == "wol":
            mac = meta.get("mac")
            iface = meta.get("wol_iface", "eth0")
            if not mac:
                return {"ok": False, "error": "no mac stored for node"}
            res = _run(["etherwake", "-i", iface, mac])
            if not res.get("ok"):
                res = _run(["wakeonlan", mac])
        elif method == "ipmi":
            bmc = meta.get("bmc_ip")
            user = meta.get("bmc_user", "ADMIN")
            pw = meta.get("bmc_pass", "")
            if not bmc:
                return {"ok": False, "error": "no bmc_ip stored for node"}
            res = _run(
                ["ipmitool", "-H", bmc, "-U", user, "-P", pw, "chassis", "power", "on"]
            )
        else:
            return {"ok": False, "error": f"unknown method: {method}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if res.get("ok"):
        _update_node_state(node, power_state="active", method=method)
    _audit("wake_node", {"node": node, "method": method, "result": res})
    return {"ok": bool(res.get("ok")), "node": node, "method": method, "raw": res}


def suspend_node(node: str, method: str = "s3") -> dict[str, Any]:
    if not node:
        return {"ok": False, "error": "node required"}
    meta = _node_meta(node)
    res: dict[str, Any]
    try:
        if method == "s3":
            host = meta.get("hostname") or node
            if host in ("localhost", "127.0.0.1", os.uname().nodename if hasattr(os, "uname") else ""):
                res = _run(["systemctl", "suspend"])
            else:
                res = _run(["ssh", host, "systemctl suspend"])
        elif method == "ipmi":
            bmc = meta.get("bmc_ip")
            user = meta.get("bmc_user", "ADMIN")
            pw = meta.get("bmc_pass", "")
            if not bmc:
                return {"ok": False, "error": "no bmc_ip stored for node"}
            res = _run(
                ["ipmitool", "-H", bmc, "-U", user, "-P", pw, "chassis", "power", "off"]
            )
        else:
            return {"ok": False, "error": f"unknown method: {method}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if res.get("ok"):
        est_w = estimate_node_power_w(node)
        _update_node_state(node, power_state="suspended", method=method)
        _audit(
            "suspend_node",
            {"node": node, "method": method, "result": res, "estimated_w": est_w},
            kwh_saved=est_w / 1000.0,  # 1h baseline
        )
    else:
        _audit("suspend_node", {"node": node, "method": method, "result": res})
    return {"ok": bool(res.get("ok")), "node": node, "method": method, "raw": res}


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

def get_history(days: int = 7) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(days or 7)))
    out: list[dict[str, Any]] = []
    try:
        with AUDIT_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get("ts", "")
                try:
                    t = datetime.fromisoformat(ts.replace("Z", ""))
                except Exception:
                    out.append(e)
                    continue
                if t >= cutoff:
                    out.append(e)
    except Exception:
        return out
    return out


__all__ = [
    "get_config",
    "set_config",
    "analyze_savings_potential",
    "get_green_score",
    "predict_load_window",
    "recommend_consolidation",
    "enter_green_window",
    "wake_node",
    "suspend_node",
    "list_node_states",
    "get_history",
    "estimate_node_power_w",
]






