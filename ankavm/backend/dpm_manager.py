"""
ankavm DPM — Distributed Power Management
Monitors cluster node utilization and recommends/executes power actions.
Storage: /var/lib/ankavm/dpm_config.json
"""
import json, logging, threading, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ankavm.dpm")
_CONFIG_FILE = Path("/var/lib/ankavm/dpm_config.json")
_lock = threading.Lock()

DEFAULT_CONFIG = {
    "enabled": False,
    "cpu_low_threshold": 15,    # % below which a node is "idle"
    "cpu_high_threshold": 80,   # % above which a node needs help
    "idle_minutes": 20,         # minutes below threshold before action
    "action": "recommend",      # recommend | suspend | wakeup
    "wakeol_enabled": False,    # Wake-on-LAN for suspended nodes
    "nodes": [],                # list of {ip, mac, name, last_checked}
}


def _load():
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text())
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def _save(cfg):
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_config():
    with _lock:
        return _load()


def save_config(**kwargs):
    with _lock:
        cfg = _load()
        allowed = {"enabled", "cpu_low_threshold", "cpu_high_threshold",
                   "idle_minutes", "action", "wakeol_enabled"}
        for k, v in kwargs.items():
            if k in allowed:
                cfg[k] = v
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save(cfg)
        return cfg


def add_node(ip, name="", mac=""):
    with _lock:
        cfg = _load()
        existing = [n for n in cfg.get("nodes", []) if n["ip"] == ip]
        if not existing:
            cfg.setdefault("nodes", []).append({
                "ip": ip, "name": name or ip, "mac": mac,
                "added_at": datetime.now(timezone.utc).isoformat(),
            })
            _save(cfg)
            return True
        return False


def remove_node(ip):
    with _lock:
        cfg = _load()
        orig = len(cfg.get("nodes", []))
        cfg["nodes"] = [n for n in cfg.get("nodes", []) if n["ip"] != ip]
        if len(cfg["nodes"]) < orig:
            _save(cfg)
            return True
    return False


def _get_node_cpu(ip):
    """SSH into node and get CPU idle %."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
             f"root@{ip}",
             "top -bn1 | grep 'Cpu(s)' | awk '{print $8}' | tr -d '%id,'"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            idle = float(r.stdout.strip())
            return round(100.0 - idle, 1)
    except Exception:
        pass
    return None


def _wake_node(mac):
    """Send WoL magic packet."""
    try:
        subprocess.run(["wakeonlan", mac], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def analyze():
    """Check all registered nodes and return power recommendations."""
    cfg = _load()
    low_thr  = cfg.get("cpu_low_threshold", 15)
    high_thr = cfg.get("cpu_high_threshold", 80)
    recommendations = []

    for node in cfg.get("nodes", []):
        cpu = _get_node_cpu(node["ip"])
        if cpu is None:
            recommendations.append({
                "node": node["ip"], "name": node["name"],
                "cpu": None, "status": "unreachable",
                "action": "check_node",
            })
            continue

        if cpu < low_thr:
            rec = "suspend" if cfg.get("action") == "suspend" else "recommend_suspend"
        elif cpu > high_thr:
            rec = "high_load"
        else:
            rec = "normal"

        recommendations.append({
            "node": node["ip"], "name": node["name"],
            "cpu": cpu, "status": "online", "action": rec,
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "low_threshold": low_thr,
        "high_threshold": high_thr,
        "nodes": recommendations,
    }


def wakeup_node(ip):
    """Attempt to wake a suspended node via WoL."""
    cfg = _load()
    node = next((n for n in cfg.get("nodes", []) if n["ip"] == ip), None)
    if not node:
        return {"ok": False, "error": "Node not found"}
    mac = node.get("mac", "")
    if not mac:
        return {"ok": False, "error": "No MAC address registered for this node"}
    result = _wake_node(mac)
    return {"ok": result, "mac": mac, "ip": ip}






