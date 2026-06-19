"""
service_chain.py â€” Service Chaining (IDS â†’ WAF â†’ LB â†’ VM traffic steering)
ankavm v2.5.9 Network Advanced 2

Features:
  - create_chain(name, hops, ingress, egress) â€” iptables/nftables mark+route chain
  - list_chains(), get_chain(name), delete_chain(name)
  - get_chain_stats(name) â€” packet count per hop (iptables -L -v)

Config persisted to /var/lib/ankavm/service_chains.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.

Hop types: 'ids' | 'waf' | 'lb' | 'vm'
Steering mechanism: iptables MARK + ip rule routing (policy-based routing)
"""

from __future__ import annotations
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("service_chain")

_CHAIN_FILE   = Path("/var/lib/ankavm/service_chains.json")
_MARK_BASE    = 0x0C00   # 0x0C00â€“0x0CFF reserved for service chains (256 chains max)
_lock         = threading.Lock()


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _CHAIN_FILE.exists():
            return json.loads(_CHAIN_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("svcchain load fail: %s", e)
    return {}


def _save(data: dict) -> None:
    try:
        _CHAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CHAIN_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_CHAIN_FILE)
    except Exception as e:
        log.warning("svcchain save fail: %s", e)


# â”€â”€ iptables helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ipt_available() -> bool:
    try:
        r = subprocess.run(["iptables", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _iptables(*args, timeout: int = 5) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["iptables"] + list(args),
        capture_output=True, text=True, timeout=timeout,
    )


def _iptables_chain_name(chain_name: str) -> str:
    safe = chain_name.replace("-", "_").replace(".", "_").upper()
    return f"OXSC_{safe[:20]}"


def _allocate_mark(name: str, existing: dict) -> int:
    """Assign a unique MARK value for the chain."""
    used = {v.get("mark", 0) for v in existing.values()}
    for offset in range(256):
        m = _MARK_BASE + offset
        if m not in used:
            return m
    return _MARK_BASE  # Reuse base as last resort


def _create_iptables_chain(ipt_chain: str, mark: int,
                            ingress: str, egress: str, hops: list) -> dict:
    """
    Create an iptables chain that:
      1. Marks ingress traffic with <mark>
      2. Adds per-hop FORWARD rules with comments
      3. Routes marked traffic via policy-based routing (ip rule)
    """
    errors = []

    # 1. Create the chain
    r = _iptables("-N", ipt_chain)
    if r.returncode != 0 and "already exists" not in r.stderr:
        errors.append(f"chain create: {r.stderr.strip()}")

    # 2. Mark ingress traffic
    r = _iptables(
        "-A", "PREROUTING", "-t", "mangle",
        "-i", ingress,
        "-j", "MARK", "--set-mark", hex(mark),
    )
    if r.returncode != 0:
        errors.append(f"prerouting mark: {r.stderr.strip()}")

    # 3. Per-hop FORWARD jump
    for i, hop in enumerate(hops):
        target  = hop.get("target", "")
        hop_type = hop.get("type", "vm")
        comment = f"oxsc_hop_{i}_{hop_type}"
        r = _iptables(
            "-A", "FORWARD",
            "-m", "mark", "--mark", hex(mark),
            "-m", "comment", "--comment", comment,
            "-d", target,
            "-j", "ACCEPT",
        )
        if r.returncode != 0:
            errors.append(f"hop {i} ({hop_type}): {r.stderr.strip()}")

    # 4. Policy-based route for marked traffic â†’ egress
    try:
        subprocess.run(
            ["ip", "rule", "add", "fwmark", hex(mark), "table", str(100 + (mark & 0xFF))],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["ip", "route", "add", "default", "dev", egress,
             "table", str(100 + (mark & 0xFF))],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        errors.append(f"ip rule/route: {e}")

    return {"errors": errors}


def _delete_iptables_chain(ipt_chain: str, mark: int,
                            ingress: str, egress: str) -> None:
    try:
        # Remove prerouting mark
        _iptables(
            "-D", "PREROUTING", "-t", "mangle",
            "-i", ingress,
            "-j", "MARK", "--set-mark", hex(mark),
        )
        # Flush & delete chain
        _iptables("-F", ipt_chain)
        _iptables("-X", ipt_chain)
        # Remove policy route
        table = str(100 + (mark & 0xFF))
        subprocess.run(["ip", "rule", "del", "fwmark", hex(mark), "table", table],
                       capture_output=True, timeout=5)
        subprocess.run(["ip", "route", "flush", "table", table],
                       capture_output=True, timeout=5)
    except Exception as e:
        log.warning("svcchain delete cleanup error: %s", e)


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_chain(name: str, hops: list, ingress: str, egress: str) -> dict:
    """
    Create a service chain.
    hops: [{type:'ids'|'waf'|'lb'|'vm', target:<ip_or_iface>}]
    ingress/egress: network interface names
    """
    with _lock:
        data = _load()
        if name in data:
            return {"ok": False, "error": f"Chain '{name}' already exists"}

        mark      = _allocate_mark(name, data)
        ipt_chain = _iptables_chain_name(name)
        errors    = []

        if _ipt_available():
            result = _create_iptables_chain(ipt_chain, mark, ingress, egress, hops)
            errors = result.get("errors", [])
        else:
            log.warning("svcchain: iptables not available â€” storing chain config only")

        data[name] = {
            "name":       name,
            "hops":       hops,
            "ingress":    ingress,
            "egress":     egress,
            "ipt_chain":  ipt_chain,
            "mark":       mark,
            "active":     True,
            "created_at": int(time.time()),
        }
        _save(data)

        return {
            "ok":        True,
            "name":      name,
            "mark":      hex(mark),
            "ipt_chain": ipt_chain,
            "hops":      len(hops),
            "errors":    errors,
        }


def list_chains() -> list:
    with _lock:
        return list(_load().values())


def get_chain(name: str) -> Optional[dict]:
    with _lock:
        return _load().get(name)


def delete_chain(name: str) -> dict:
    with _lock:
        data = _load()
        if name not in data:
            return {"ok": False, "error": "Chain not found"}
        entry = data[name]
        if _ipt_available():
            _delete_iptables_chain(
                entry.get("ipt_chain", ""),
                entry.get("mark", 0),
                entry.get("ingress", ""),
                entry.get("egress", ""),
            )
        del data[name]
        _save(data)
        return {"ok": True, "name": name}


def get_chain_stats(name: str) -> dict:
    """
    Return per-hop packet/byte counters from iptables -L -v -n --line-numbers.
    Falls back to stored config if iptables unavailable.
    """
    with _lock:
        data = _load()
        entry = data.get(name)
        if not entry:
            return {"ok": False, "error": "Chain not found"}

        hops        = entry.get("hops", [])
        ipt_chain   = entry.get("ipt_chain", "")
        mark        = entry.get("mark", 0)
        hop_stats   = []

        if _ipt_available() and ipt_chain:
            try:
                r = _iptables("-L", "FORWARD", "-v", "-n", "--line-numbers", timeout=10)
                if r.returncode == 0:
                    for i, hop in enumerate(hops):
                        comment = f"oxsc_hop_{i}_{hop.get('type', 'vm')}"
                        pkts, byts = 0, 0
                        for line in r.stdout.splitlines():
                            if comment in line:
                                parts = line.split()
                                if len(parts) >= 2:
                                    try:
                                        pkts = int(parts[0])
                                        byts = int(parts[1])
                                    except ValueError:
                                        pass
                        hop_stats.append({
                            "hop":    i,
                            "type":   hop.get("type"),
                            "target": hop.get("target"),
                            "pkts":   pkts,
                            "bytes":  byts,
                        })
            except Exception as e:
                log.warning("svcchain stats iptables fail: %s", e)

        if not hop_stats:
            for i, hop in enumerate(hops):
                hop_stats.append({
                    "hop":    i,
                    "type":   hop.get("type"),
                    "target": hop.get("target"),
                    "pkts":   None,
                    "bytes":  None,
                })

        return {
            "ok":        True,
            "name":      name,
            "mark":      hex(mark),
            "hops":      hop_stats,
        }






