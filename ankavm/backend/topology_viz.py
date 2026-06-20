"""
topology_viz.py — Topology + Flow Visualization (LLDP / ARP / conntrack)
ankavm v2.5.8 Observability

Note: The existing topology.py provides basic node/network info.
      This module adds:
        - get_topology()  → {nodes, edges} graph from ARP + virsh + domiflist
        - get_lldp_neighbors() → lldpctl -f json parse (graceful empty if absent)
        - get_flow_matrix()    → conntrack -L parse (graceful empty if absent)

      Paths: /api/topo-viz/*  (avoids clash with existing /api/topology endpoint)
"""

from __future__ import annotations
import json
import logging
import subprocess
import threading
from typing import Optional

log = logging.getLogger("topology_viz")
_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except FileNotFoundError:
        log.debug("command not found: %s", cmd[0])
    except subprocess.TimeoutExpired:
        log.debug("timeout: %s", " ".join(cmd))
    except Exception as e:
        log.debug("run fail %s: %s", cmd, e)
    return ""


def _parse_arp() -> list:
    """Parse `arp -n` output → list of {ip, mac, iface}."""
    out = _run(["arp", "-n"])
    entries = []
    for line in out.splitlines():
        parts = line.split()
        # typical: 192.168.x.x  ether  aa:bb:cc  C  virbr0
        if len(parts) >= 5 and ":" in parts[2]:
            entries.append({"ip": parts[0], "mac": parts[2], "iface": parts[4]})
    return entries


def _virsh_net_list() -> list:
    """Return list of libvirt network names."""
    out = _run(["virsh", "net-list", "--all"])
    networks = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if parts:
            networks.append(parts[0])
    return networks


def _virsh_domlist() -> list:
    """Return list of {id, name, state} for all domains."""
    out = _run(["virsh", "list", "--all"])
    domains = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 3:
            domains.append({"id": parts[0], "name": parts[1], "state": parts[2]})
    return domains


def _virsh_domiflist(vm_name: str) -> list:
    """Return list of {iface, type, source, model, mac} for a domain."""
    out = _run(["virsh", "domiflist", vm_name])
    ifaces = []
    for line in out.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 5:
            ifaces.append({
                "iface":  parts[0],
                "type":   parts[1],
                "source": parts[2],
                "model":  parts[3],
                "mac":    parts[4],
            })
    return ifaces


# ── Public API ────────────────────────────────────────────────────────────────

def get_topology() -> dict:
    """
    Build a topology graph {nodes:[], edges:[]} by combining:
      - libvirt networks
      - libvirt VM list + domiflist
      - ARP table
    """
    nodes: list = []
    edges: list = []
    node_ids: set = set()

    def add_node(nid: str, label: str, kind: str, **extra):
        if nid not in node_ids:
            node_ids.add(nid)
            nodes.append({"id": nid, "label": label, "kind": kind, **extra})

    # Host node
    add_node("host", "host", "host")

    # Networks
    for net_name in _virsh_net_list():
        nid = f"net:{net_name}"
        add_node(nid, net_name, "network")
        edges.append({"source": "host", "target": nid, "relation": "bridges"})

    # VMs + their NICs
    mac_to_vm: dict = {}
    for dom in _virsh_domlist():
        vm_name = dom["name"]
        vm_nid  = f"vm:{vm_name}"
        add_node(vm_nid, vm_name, "vm", state=dom["state"])
        for iface in _virsh_domiflist(vm_name):
            src_net = iface.get("source", "")
            net_nid = f"net:{src_net}" if src_net else "host"
            edges.append({
                "source":   vm_nid,
                "target":   net_nid,
                "relation": "attached",
                "mac":      iface.get("mac", ""),
                "model":    iface.get("model", ""),
            })
            if iface.get("mac"):
                mac_to_vm[iface["mac"].lower()] = vm_nid

    # ARP: annotate VM nodes with IP addresses
    for arp in _parse_arp():
        mac = arp["mac"].lower()
        if mac in mac_to_vm:
            vm_nid = mac_to_vm[mac]
            for node in nodes:
                if node["id"] == vm_nid:
                    node.setdefault("ips", [])
                    node["ips"].append(arp["ip"])

    return {"nodes": nodes, "edges": edges}


def get_lldp_neighbors() -> list:
    """
    Return LLDP neighbor list from `lldpctl -f json`.
    Returns [] gracefully if lldpctl is not installed.
    """
    out = _run(["lldpctl", "-f", "json"])
    if not out.strip():
        return []
    try:
        data = json.loads(out)
        # lldpctl JSON: {"lldp":{"interface":{...}}}
        ifaces = data.get("lldp", {}).get("interface", {})
        if isinstance(ifaces, dict):
            ifaces = list(ifaces.values())
        neighbors = []
        for iface in ifaces:
            if not isinstance(iface, dict):
                continue
            # Each interface may have one port block
            port = iface.get("port", {})
            chassis = iface.get("chassis", {})
            # chassis may be a dict keyed by name
            if isinstance(chassis, dict):
                ch_vals = list(chassis.values())
                chassis_name = ch_vals[0].get("name", {}).get("value", "") if ch_vals else ""
            else:
                chassis_name = ""
            neighbors.append({
                "local_iface": iface.get("name", ""),
                "chassis":     chassis_name,
                "port_id":     port.get("id", {}).get("value", "") if isinstance(port, dict) else "",
                "port_desc":   port.get("descr", {}).get("value", "") if isinstance(port, dict) else "",
            })
        return neighbors
    except Exception as e:
        log.debug("lldp parse fail: %s", e)
        return []


def get_flow_matrix() -> list:
    """
    Return VM-to-VM traffic flows from conntrack.
    Tries `conntrack -L` first; falls back to /proc/net/nf_conntrack.
    Returns [] gracefully if neither is available.
    """
    flows: list = []

    # Try conntrack command
    ct_out = _run(["conntrack", "-L"], timeout=10)
    if not ct_out.strip():
        # Try /proc/net/nf_conntrack
        try:
            with open("/proc/net/nf_conntrack", encoding="utf-8", errors="replace") as f:
                ct_out = f.read()
        except Exception:
            return []

    for line in ct_out.splitlines():
        parts = line.split()
        # conntrack output: <l3proto> <l4proto_num> <proto_name> <timeout> src=... dst=... ...
        flow: dict = {}
        for part in parts:
            if "=" in part:
                k, _, v = part.partition("=")
                if k in ("src", "dst", "sport", "dport", "proto"):
                    # first occurrence = original direction; handle duplicates
                    if k not in flow:
                        flow[k] = v
        if "src" in flow and "dst" in flow:
            # Find proto from line
            proto = next((p for p in parts if p in ("tcp", "udp", "icmp")), "")
            flow["proto"] = proto or flow.get("proto", "")
            flows.append(flow)
        if len(flows) >= 500:
            break

    return flows






