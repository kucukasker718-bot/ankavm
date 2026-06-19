"""
bfd_manager.py â€” Bidirectional Forwarding Detection
ankavm v2.5.9 Network Advanced 2

Features:
  - configure_bfd(peer_ip, interval_ms, multiplier) â€” bfdd/frr if available,
    otherwise ICMP-based fallback poll registration (no background thread)
  - get_bfd_sessions() â€” active BFD sessions + status (up/down/lag)
  - remove_bfd(peer_ip)
  - check_peer(peer_ip) â€” on-demand liveness via ping RTT

Config persisted to /var/lib/ankavm/bfd_sessions.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("bfd_manager")

_SESSION_FILE = Path("/var/lib/ankavm/bfd_sessions.json")
_lock         = threading.Lock()


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _SESSION_FILE.exists():
            return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("bfd load fail: %s", e)
    return {}


def _save(data: dict) -> None:
    try:
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SESSION_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_SESSION_FILE)
    except Exception as e:
        log.warning("bfd save fail: %s", e)


# â”€â”€ BFD daemon / FRR helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _bfdd_available() -> bool:
    try:
        r = subprocess.run(["which", "bfdd"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True
        r2 = subprocess.run(["which", "vtysh"], capture_output=True, timeout=5)
        return r2.returncode == 0
    except Exception:
        return False


def _frr_configure_bfd(peer_ip: str, interval_ms: int, multiplier: int) -> dict:
    """Configure BFD via FRR vtysh."""
    try:
        vtysh_cmds = (
            f"configure terminal\n"
            f"bfd\n"
            f"peer {peer_ip}\n"
            f"  detect-multiplier {multiplier}\n"
            f"  receive-interval {interval_ms}\n"
            f"  transmit-interval {interval_ms}\n"
            f"  no shutdown\n"
            f"exit\n"
            f"exit\n"
        )
        r = subprocess.run(
            ["vtysh", "-c", vtysh_cmds],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return {"ok": True, "backend": "frr"}
        log.warning("frr bfd config fail: %s", r.stderr.strip())
        return {"ok": False, "error": r.stderr.strip(), "backend": "frr"}
    except Exception as e:
        return {"ok": False, "error": str(e), "backend": "frr"}


def _frr_get_bfd_peers() -> list:
    """Parse FRR BFD peer state via vtysh."""
    try:
        r = subprocess.run(
            ["vtysh", "-c", "show bfd peers brief"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return []
        peers = []
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and _is_ip(parts[0]):
                peers.append({
                    "peer_ip":    parts[0],
                    "status":     parts[1].lower(),
                    "uptime":     parts[2] if len(parts) > 2 else "N/A",
                    "backend":    "frr",
                })
        return peers
    except Exception as e:
        log.warning("frr bfd peers fail: %s", e)
        return []


def _frr_remove_bfd(peer_ip: str) -> dict:
    try:
        vtysh_cmds = (
            f"configure terminal\nbfd\nno peer {peer_ip}\nexit\nexit\n"
        )
        r = subprocess.run(
            ["vtysh", "-c", vtysh_cmds],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return {"ok": True, "backend": "frr"}
        return {"ok": False, "error": r.stderr.strip(), "backend": "frr"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# â”€â”€ Ping / ICMP fallback helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ping_rtt(ip: str, count: int = 3, timeout: int = 5) -> dict:
    """On-demand ICMP ping â€” returns {reachable, rtt_ms, loss_pct}."""
    try:
        r = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), ip],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        output = r.stdout + r.stderr
        reachable = r.returncode == 0

        rtt_ms   = None
        loss_pct = 100

        import re
        # Extract avg RTT from "rtt min/avg/max/mdev = 0.1/0.2/0.3/0.0 ms"
        m = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", output)
        if m:
            rtt_ms = float(m.group(1))
        # Extract packet loss
        lm = re.search(r"(\d+)% packet loss", output)
        if lm:
            loss_pct = int(lm.group(1))

        return {
            "reachable": reachable,
            "rtt_ms":    rtt_ms,
            "loss_pct":  loss_pct,
        }
    except Exception as e:
        return {"reachable": False, "rtt_ms": None, "loss_pct": 100, "error": str(e)}


def _is_ip(s: str) -> bool:
    import re
    return bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", s))


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def configure_bfd(peer_ip: str, interval_ms: int = 300, multiplier: int = 3) -> dict:
    """
    Configure BFD for peer_ip.
    Uses FRR/bfdd if available; otherwise registers an ICMP-fallback entry
    (manual check_peer() calls â€” no background polling thread).
    """
    with _lock:
        data   = _load()
        use_frr = _bfdd_available()
        result  = {}

        if use_frr:
            result = _frr_configure_bfd(peer_ip, interval_ms, multiplier)
        else:
            log.info("bfd: frr/bfdd not available â€” registering ICMP fallback for %s", peer_ip)
            result = {"ok": True, "backend": "icmp_fallback"}

        if result.get("ok", False):
            data[peer_ip] = {
                "peer_ip":     peer_ip,
                "interval_ms": interval_ms,
                "multiplier":  multiplier,
                "backend":     result.get("backend", "unknown"),
                "status":      "configured",
                "created_at":  int(time.time()),
                "last_check":  None,
            }
            _save(data)

        return {
            "ok":          result.get("ok", False),
            "peer_ip":     peer_ip,
            "interval_ms": interval_ms,
            "multiplier":  multiplier,
            "backend":     result.get("backend", "unknown"),
            "error":       result.get("error"),
        }


def get_bfd_sessions() -> list:
    """Return all BFD sessions with current status."""
    with _lock:
        data = _load()
        if not data:
            return []

        # Try to get live status from FRR first
        frr_live = {}
        if _bfdd_available():
            for peer in _frr_get_bfd_peers():
                frr_live[peer["peer_ip"]] = peer

        sessions = []
        for peer_ip, entry in data.items():
            if peer_ip in frr_live:
                entry = {**entry, "status": frr_live[peer_ip]["status"],
                         "uptime": frr_live[peer_ip].get("uptime")}
            sessions.append(entry)
        return sessions


def remove_bfd(peer_ip: str) -> dict:
    with _lock:
        data = _load()
        if peer_ip not in data:
            return {"ok": False, "error": "Session not found"}
        entry = data[peer_ip]
        result: dict = {"ok": True}
        if _bfdd_available() and entry.get("backend") != "icmp_fallback":
            result = _frr_remove_bfd(peer_ip)
        del data[peer_ip]
        _save(data)
        return {"ok": result.get("ok", True), "peer_ip": peer_ip}


def check_peer(peer_ip: str) -> dict:
    """On-demand liveness check via ICMP ping (also updates last_check in store)."""
    ping = _ping_rtt(peer_ip)
    with _lock:
        data = _load()
        if peer_ip in data:
            data[peer_ip]["last_check"] = int(time.time())
            data[peer_ip]["last_rtt_ms"] = ping.get("rtt_ms")
            data[peer_ip]["status"] = "up" if ping["reachable"] else "down"
            _save(data)
    return {
        "peer_ip":   peer_ip,
        "reachable": ping["reachable"],
        "rtt_ms":    ping.get("rtt_ms"),
        "loss_pct":  ping.get("loss_pct", 100),
        "checked_at": int(time.time()),
    }






