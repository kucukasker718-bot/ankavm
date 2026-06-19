"""
ankavm Multi-Region Manager
Geo-aware VM placement, cross-region replication, latency-aware DRS.
State: /var/lib/ankavm/regions.json
"""

import json
import math
import os
import time
from pathlib import Path

STATE_DIR = Path("/var/lib/ankavm")
STATE_FILE = STATE_DIR / "regions.json"
LOG_DIR = Path("/var/log/ankavm")
LOG_FILE = LOG_DIR / "multi_region.jsonl"


def _ensure_dirs():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass


def _load_state() -> dict:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return {"regions": {}, "replications": [], "failovers": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"regions": {}, "replications": [], "failovers": []}


def _save_state(state: dict) -> None:
    _ensure_dirs()
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _audit(action: str, payload: dict) -> None:
    _ensure_dirs()
    entry = {"ts": time.time(), "action": action, **payload}
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def list_regions() -> list:
    state = _load_state()
    out = []
    for name, r in state["regions"].items():
        out.append({
            "name": name,
            "endpoint": r["endpoint"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "timezone": r["timezone"],
            "weight": r["weight"],
            "latency_ms": r.get("latency_ms", 0.0),
            "status": r.get("status", "unknown"),
            "updated_at": r.get("updated_at", 0),
        })
    return out


def add_region(name: str, endpoint: str, latitude: float, longitude: float,
               timezone: str, weight: float = 1.0) -> dict:
    if not name or not endpoint:
        raise ValueError("name and endpoint required")
    state = _load_state()
    if name in state["regions"]:
        raise ValueError(f"region {name} already exists")
    region = {
        "endpoint": endpoint,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "timezone": timezone,
        "weight": float(weight),
        "latency_ms": 0.0,
        "status": "active",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    state["regions"][name] = region
    _save_state(state)
    _audit("add_region", {"name": name, "endpoint": endpoint})
    return {"name": name, **region}


def remove_region(name: str) -> dict:
    state = _load_state()
    if name not in state["regions"]:
        raise KeyError(f"region {name} not found")
    del state["regions"][name]
    _save_state(state)
    _audit("remove_region", {"name": name})
    return {"removed": name, "ok": True}


def get_region(name: str) -> dict:
    state = _load_state()
    if name not in state["regions"]:
        raise KeyError(f"region {name} not found")
    return {"name": name, **state["regions"][name]}


def update_region_latency(name: str, latency_ms: float) -> dict:
    state = _load_state()
    if name not in state["regions"]:
        raise KeyError(f"region {name} not found")
    state["regions"][name]["latency_ms"] = float(latency_ms)
    state["regions"][name]["updated_at"] = time.time()
    if latency_ms < 0:
        state["regions"][name]["status"] = "down"
    elif latency_ms > 500:
        state["regions"][name]["status"] = "degraded"
    else:
        state["regions"][name]["status"] = "active"
    _save_state(state)
    _audit("update_latency", {"name": name, "latency_ms": latency_ms})
    return {"name": name, **state["regions"][name]}


def place_vm(vm_spec: dict, prefer_region=None, user_location=None) -> dict:
    state = _load_state()
    if not state["regions"]:
        raise RuntimeError("no regions registered")

    if prefer_region and prefer_region in state["regions"]:
        r = state["regions"][prefer_region]
        if r.get("status") == "active":
            return {"region": prefer_region, "reason": "preferred", "score": 0.0,
                    "vm_spec": vm_spec, **r}

    scores = []
    for name, r in state["regions"].items():
        if r.get("status") == "down":
            continue
        distance_km = 0.0
        if user_location:
            try:
                lat, lon = user_location
                distance_km = _haversine_km(lat, lon, r["latitude"], r["longitude"])
            except (TypeError, ValueError):
                distance_km = 0.0
        latency = r.get("latency_ms", 0.0)
        weight = r.get("weight", 1.0) or 0.01
        score = (distance_km * 0.05 + latency) / weight
        scores.append((score, name, r, distance_km))

    if not scores:
        raise RuntimeError("no active regions available")

    scores.sort(key=lambda x: x[0])
    score, name, r, distance_km = scores[0]
    result = {
        "region": name,
        "reason": "best_score",
        "score": score,
        "distance_km": distance_km,
        "latency_ms": r.get("latency_ms", 0.0),
        "vm_spec": vm_spec,
        "endpoint": r["endpoint"],
    }
    _audit("place_vm", {"region": name, "score": score})
    return result


def replicate_snapshot(vm_id: str, source_region: str, target_region: str) -> dict:
    state = _load_state()
    if source_region not in state["regions"]:
        raise KeyError(f"source {source_region} not found")
    if target_region not in state["regions"]:
        raise KeyError(f"target {target_region} not found")
    rep = {
        "vm_id": vm_id,
        "source": source_region,
        "target": target_region,
        "status": "queued",
        "lag_seconds": 0,
        "created_at": time.time(),
    }
    state["replications"].append(rep)
    _save_state(state)
    _audit("replicate", rep)
    return rep


def get_replication_status() -> list:
    state = _load_state()
    now = time.time()
    out = []
    for rep in state["replications"]:
        lag = now - rep.get("created_at", now)
        out.append({**rep, "lag_seconds": int(lag)})
    return out


def failover_to_region(vm_id: str, target_region: str) -> dict:
    state = _load_state()
    if target_region not in state["regions"]:
        raise KeyError(f"target {target_region} not found")
    event = {
        "vm_id": vm_id,
        "target": target_region,
        "status": "initiated",
        "ts": time.time(),
    }
    state["failovers"].append(event)
    _save_state(state)
    _audit("failover", event)
    return event


def get_topology() -> dict:
    state = _load_state()
    nodes = []
    for name, r in state["regions"].items():
        nodes.append({
            "id": name,
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "status": r.get("status", "unknown"),
            "weight": r.get("weight", 1.0),
        })
    edges = []
    seen = set()
    for rep in state["replications"]:
        key = (rep["source"], rep["target"])
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": rep["source"], "target": rep["target"]})
    return {"nodes": nodes, "edges": edges, "generated_at": time.time()}






