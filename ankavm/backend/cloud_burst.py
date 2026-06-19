"""
ankavm Cloud Burst Manager
When local cluster load exceeds threshold, provision burst VMs in AWS/GCP/Azure.
Tracks burst nodes, costs, lifecycle. Auto-retire when local load drops.
State: /var/lib/ankavm/cloud_burst.json
NO periodic loop â€” caller (e.g. green_mode or DRS) triggers check_and_burst().
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

STATE_DIR = Path("/var/lib/ankavm")
STATE_FILE = STATE_DIR / "cloud_burst.json"
LOG_DIR = Path("/var/log/ankavm")
AUDIT_LOG = LOG_DIR / "cloud_burst.jsonl"

DEFAULT_CONFIG = {
    "enabled": False,
    "providers": ["aws"],
    "burst_threshold_pct": 80.0,
    "retire_threshold_pct": 50.0,
    "max_nodes": 10,
    "default_instance_type": {
        "aws": "t3.medium",
        "gcp": "e2-standard-2",
        "azure": "Standard_B2s",
    },
    "hourly_cost_usd": {
        "aws": 0.0416,
        "gcp": 0.0470,
        "azure": 0.0496,
    },
}


def _ensure_dirs():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass


def _load_state() -> dict:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return {"config": dict(DEFAULT_CONFIG), "nodes": [], "migrations": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                state.setdefault("config", {}).setdefault(k, v)
            state.setdefault("nodes", [])
            state.setdefault("migrations", [])
            return state
    except (json.JSONDecodeError, OSError):
        return {"config": dict(DEFAULT_CONFIG), "nodes": [], "migrations": []}


def _save_state(state: dict) -> None:
    _ensure_dirs()
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _audit(action: str, cost_estimate_usd: float = 0.0, **payload) -> None:
    _ensure_dirs()
    entry = {
        "ts": time.time(),
        "action": action,
        "cost_estimate_usd": cost_estimate_usd,
        **payload,
    }
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def get_config() -> dict:
    return _load_state()["config"]


def set_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError("config must be dict")
    state = _load_state()
    state["config"].update(cfg)
    _save_state(state)
    _audit("set_config", config=cfg)
    return state["config"]


def get_burst_nodes() -> list:
    return _load_state()["nodes"]


def check_should_burst(local_load_pct: float) -> dict:
    state = _load_state()
    cfg = state["config"]
    current = len(state["nodes"])
    threshold = cfg.get("burst_threshold_pct", 80.0)
    max_nodes = cfg.get("max_nodes", 10)

    if not cfg.get("enabled", False):
        return {"burst_needed": False, "recommended_count": 0,
                "reason": "burst disabled in config"}
    if current >= max_nodes:
        return {"burst_needed": False, "recommended_count": 0,
                "reason": f"max nodes ({max_nodes}) already running"}
    if local_load_pct < threshold:
        return {"burst_needed": False, "recommended_count": 0,
                "reason": f"load {local_load_pct:.1f}% below threshold {threshold:.1f}%"}

    over = local_load_pct - threshold
    recommended = max(1, int(over // 10) + 1)
    recommended = min(recommended, max_nodes - current)
    return {
        "burst_needed": True,
        "recommended_count": recommended,
        "reason": f"load {local_load_pct:.1f}% over threshold {threshold:.1f}%",
    }


def _try_cli(provider: str, instance_type: str) -> dict:
    cli_map = {
        "aws": ["aws", "ec2", "run-instances", "--instance-type", instance_type,
                "--count", "1", "--output", "json"],
        "gcp": ["gcloud", "compute", "instances", "create",
                f"ankavm-burst-{uuid.uuid4().hex[:8]}",
                "--machine-type", instance_type, "--format", "json"],
        "azure": ["az", "vm", "create", "--name",
                  f"ankavm-burst-{uuid.uuid4().hex[:8]}",
                  "--size", instance_type, "--output", "json"],
    }
    cmd = cli_map.get(provider)
    if not cmd:
        raise ValueError(f"unknown provider {provider}")
    if not shutil.which(cmd[0]):
        return {"stub": True, "reason": f"{cmd[0]} CLI not found"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=120, check=False)
        if result.returncode != 0:
            return {"stub": True, "reason": f"CLI exit {result.returncode}",
                    "stderr": result.stderr[:500]}
        try:
            return {"stub": False, "data": json.loads(result.stdout)}
        except json.JSONDecodeError:
            return {"stub": False, "data": {"raw": result.stdout[:500]}}
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"stub": True, "reason": str(e)}


def provision_burst_node(provider: str, instance_type: str = None) -> dict:
    state = _load_state()
    cfg = state["config"]
    if provider not in ("aws", "gcp", "azure"):
        raise ValueError(f"unsupported provider {provider}")
    if len(state["nodes"]) >= cfg.get("max_nodes", 10):
        raise RuntimeError("max burst nodes reached")

    if not instance_type:
        instance_type = cfg.get("default_instance_type", {}).get(provider, "t3.medium")

    cli_result = _try_cli(provider, instance_type)
    node_id = f"burst-{provider}-{uuid.uuid4().hex[:10]}"
    hourly = cfg.get("hourly_cost_usd", {}).get(provider, 0.05)
    node = {
        "node_id": node_id,
        "provider": provider,
        "instance_type": instance_type,
        "status": "running",
        "hourly_cost_usd": hourly,
        "stub": cli_result.get("stub", False),
        "stub_reason": cli_result.get("reason", ""),
        "provider_data": cli_result.get("data", {}),
        "created_at": time.time(),
    }
    state["nodes"].append(node)
    _save_state(state)
    _audit("provision", cost_estimate_usd=hourly, node_id=node_id,
           provider=provider, instance_type=instance_type,
           stub=node["stub"])
    return node


def retire_burst_node(node_id: str) -> dict:
    state = _load_state()
    node = None
    for n in state["nodes"]:
        if n["node_id"] == node_id:
            node = n
            break
    if not node:
        raise KeyError(f"node {node_id} not found")

    runtime_hours = (time.time() - node.get("created_at", time.time())) / 3600.0
    cost = runtime_hours * node.get("hourly_cost_usd", 0.0)

    state["nodes"] = [n for n in state["nodes"] if n["node_id"] != node_id]
    _save_state(state)
    _audit("retire", cost_estimate_usd=cost, node_id=node_id,
           runtime_hours=runtime_hours, provider=node.get("provider"))
    return {"retired": node_id, "runtime_hours": runtime_hours,
            "cost_estimate_usd": cost, "ok": True}


def get_burst_costs(days: int = 30) -> dict:
    _ensure_dirs()
    cutoff = time.time() - days * 86400
    total = 0.0
    by_provider = {}
    by_action = {}
    count = 0
    if AUDIT_LOG.exists():
        try:
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("ts", 0) < cutoff:
                        continue
                    cost = float(e.get("cost_estimate_usd", 0.0) or 0.0)
                    total += cost
                    count += 1
                    p = e.get("provider", "unknown")
                    by_provider[p] = by_provider.get(p, 0.0) + cost
                    a = e.get("action", "unknown")
                    by_action[a] = by_action.get(a, 0.0) + cost
        except OSError:
            pass

    state = _load_state()
    running_now = sum(n.get("hourly_cost_usd", 0.0) * 24 * days
                      for n in state["nodes"])
    return {
        "days": days,
        "total_usd": round(total, 4),
        "event_count": count,
        "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
        "by_action": {k: round(v, 4) for k, v in by_action.items()},
        "projected_running_usd": round(running_now, 4),
    }


def migrate_vm_to_burst(vm_id: str, burst_node_id: str) -> dict:
    state = _load_state()
    if not any(n["node_id"] == burst_node_id for n in state["nodes"]):
        raise KeyError(f"burst node {burst_node_id} not found")
    rec = {
        "vm_id": vm_id,
        "burst_node_id": burst_node_id,
        "status": "intent_recorded",
        "ts": time.time(),
    }
    state["migrations"].append(rec)
    _save_state(state)
    _audit("migrate", vm_id=vm_id, burst_node_id=burst_node_id)
    return rec


def get_audit_log(limit: int = 100) -> list:
    _ensure_dirs()
    if not AUDIT_LOG.exists():
        return []
    lines = []
    try:
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return lines[-limit:][::-1]






