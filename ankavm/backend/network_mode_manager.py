"""
ankavm Network Mode Manager
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Solves the NAT vs Bridge IP confusion for VM networking.

Problem: Users try to manually set IPs inside VMs but it doesn't work
         because they don't know if the VM is in NAT or Bridge mode.

Features:
  - detect_vm_network_mode(vm_id) â†’ NAT / BRIDGE / ISOLATED / UNKNOWN
  - get_network_info(vm_id) â†’ full networking context (mode, gateway, dhcp range)
  - validate_static_ip(vm_id, ip) â†’ can this IP be used statically?
  - set_static_ip_cloudinit(vm_id, ip, gateway, netmask, dns) â†’ inject via cloud-init
  - list_routable_networks() â†’ networks where static IPs work
  - get_bridge_setup_status() â†’ is oxbr0 configured?
  - suggest_ip_fix(vm_id) â†’ human-readable recommendation

All ops request-triggered, no background jobs.
"""
from __future__ import annotations
import os
import re
import json
import logging
import subprocess
import ipaddress
from pathlib import Path

log = logging.getLogger("network_mode_manager")

_STATE_FILE = Path("/var/lib/ankavm/network_modes.json")


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run(cmd: list, timeout: int = 10) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _virsh(args: list, timeout: int = 10) -> tuple[bool, str]:
    return _run(["virsh", "--quiet"] + args, timeout=timeout)


def _get_vm_xml(vm_id: str) -> str | None:
    ok, out = _virsh(["dumpxml", vm_id])
    return out if ok and "<domain" in out else None


def _parse_networks_from_xml(xml: str) -> list[dict]:
    """Extract interface definitions from VM XML."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except Exception:
        return []
    ifaces = []
    for iface in root.findall(".//interface"):
        entry = {
            "type":    iface.get("type", "unknown"),
            "source":  "",
            "mac":     "",
            "target":  "",
            "model":   "",
        }
        src = iface.find("source")
        if src is not None:
            entry["source"] = src.get("network") or src.get("bridge") or src.get("dev") or ""
        mac = iface.find("mac")
        if mac is not None:
            entry["mac"] = mac.get("address", "")
        target = iface.find("target")
        if target is not None:
            entry["target"] = target.get("dev", "")
        model = iface.find("model")
        if model is not None:
            entry["model"] = model.get("type", "")
        ifaces.append(entry)
    return ifaces


def _get_libvirt_network_info(net_name: str) -> dict:
    """Get libvirt network details."""
    ok, out = _run(["virsh", "net-dumpxml", net_name])
    if not ok or not out:
        return {}

    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(out)
    except Exception:
        return {}

    fwd = root.find("forward")
    bridge = root.find("bridge")
    ip_el = root.find("ip")
    dhcp_el = root.find(".//dhcp/range")

    mode = "isolated"
    if fwd is not None:
        mode = fwd.get("mode", "nat")

    info = {
        "name":        net_name,
        "forward_mode": mode,
        "bridge_name":  bridge.get("name", "") if bridge is not None else "",
        "subnet":       "",
        "gateway":      "",
        "dhcp_start":   "",
        "dhcp_end":     "",
    }
    if ip_el is not None:
        addr    = ip_el.get("address", "")
        prefix  = ip_el.get("prefix") or ip_el.get("netmask", "24")
        info["gateway"] = addr
        try:
            # Convert netmask to prefix length if needed
            if "." in str(prefix):
                prefix = sum(bin(int(x)).count("1") for x in prefix.split("."))
            info["subnet"] = f"{addr}/{prefix}"
        except Exception:
            info["subnet"] = addr
    if dhcp_el is not None:
        info["dhcp_start"] = dhcp_el.get("start", "")
        info["dhcp_end"]   = dhcp_el.get("end", "")
    return info


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_vm_network_mode(vm_id: str) -> dict:
    """
    Returns the network mode of the first interface of a VM.
    Modes: NAT | BRIDGE | ISOLATED | DIRECT | UNKNOWN
    """
    xml = _get_vm_xml(vm_id)
    if not xml:
        return {"mode": "UNKNOWN", "reason": "VM not found or virsh error"}

    ifaces = _parse_networks_from_xml(xml)
    if not ifaces:
        return {"mode": "UNKNOWN", "reason": "No network interfaces found"}

    results = []
    for iface in ifaces:
        itype  = iface.get("type", "")
        source = iface.get("source", "")

        if itype == "network" and source:
            net_info = _get_libvirt_network_info(source)
            fwd_mode = net_info.get("forward_mode", "isolated")
            mode = {
                "nat":      "NAT",
                "bridge":   "BRIDGE",
                "route":    "ROUTE",
                "open":     "OPEN",
                "isolated": "ISOLATED",
            }.get(fwd_mode, "UNKNOWN")
            results.append({
                "interface": iface.get("target", ""),
                "mode":      mode,
                "network":   source,
                "net_info":  net_info,
                "mac":       iface.get("mac", ""),
            })
        elif itype == "bridge":
            results.append({
                "interface": iface.get("target", ""),
                "mode":      "BRIDGE",
                "network":   source,
                "net_info":  {"forward_mode": "bridge", "bridge_name": source},
                "mac":       iface.get("mac", ""),
            })
        elif itype == "direct":
            results.append({
                "interface": iface.get("target", ""),
                "mode":      "DIRECT",
                "network":   source,
                "net_info":  {"forward_mode": "direct"},
                "mac":       iface.get("mac", ""),
            })
        else:
            results.append({
                "interface": iface.get("target", ""),
                "mode":      "UNKNOWN",
                "network":   source,
                "net_info":  {},
                "mac":       iface.get("mac", ""),
            })

    primary = results[0] if results else {"mode": "UNKNOWN"}
    return {
        "vm_id":      vm_id,
        "mode":       primary["mode"],
        "interfaces": results,
        "static_ip_supported": primary["mode"] in ("BRIDGE", "DIRECT", "OPEN"),
    }


def get_network_info(vm_id: str) -> dict:
    """Full networking context for a VM â€” mode, gateway, DHCP range, static IP guidance."""
    mode_info = detect_vm_network_mode(vm_id)
    mode      = mode_info.get("mode", "UNKNOWN")
    ifaces    = mode_info.get("interfaces", [])

    net_info = ifaces[0].get("net_info", {}) if ifaces else {}
    gateway  = net_info.get("gateway", "")
    subnet   = net_info.get("subnet", "")

    can_static = mode in ("BRIDGE", "DIRECT", "OPEN")

    if mode == "NAT":
        guidance = (
            f"VM is in NAT mode. Manually setting an IP inside the VM won't give it "
            f"a reachable upstream IP. The VM will still use the libvirt DHCP range "
            f"({net_info.get('dhcp_start','?')}â€“{net_info.get('dhcp_end','?')}) as gateway {gateway}. "
            f"For a real upstream IP, switch to bridge networking (oxbr0)."
        )
    elif mode == "BRIDGE":
        guidance = (
            f"VM is in BRIDGE mode. You can set any IP on the upstream subnet. "
            f"Use the host's gateway and the upstream network's subnet."
        )
    elif mode == "ISOLATED":
        guidance = "VM is in isolated network â€” no external connectivity."
    else:
        guidance = "Unknown network mode â€” check virsh net-dumpxml for this network."

    return {
        "vm_id":              vm_id,
        "mode":               mode,
        "static_ip_supported": can_static,
        "gateway":            gateway,
        "subnet":             subnet,
        "dhcp_start":         net_info.get("dhcp_start", ""),
        "dhcp_end":           net_info.get("dhcp_end", ""),
        "bridge_name":        net_info.get("bridge_name", ""),
        "network_name":       ifaces[0].get("network", "") if ifaces else "",
        "mac_address":        ifaces[0].get("mac", "") if ifaces else "",
        "guidance":           guidance,
        "interfaces":         ifaces,
    }


def validate_static_ip(vm_id: str, ip: str) -> dict:
    """Check whether a given IP can be statically assigned to this VM."""
    info = get_network_info(vm_id)
    mode = info["mode"]

    try:
        target_ip = ipaddress.ip_address(ip)
    except ValueError:
        return {"valid": False, "reason": f"Invalid IP address: {ip}"}

    if mode == "NAT":
        # In NAT mode, static IP works only within the libvirt subnet
        subnet = info.get("subnet", "")
        if subnet:
            try:
                net = ipaddress.ip_network(subnet, strict=False)
                if target_ip in net:
                    return {
                        "valid":   True,
                        "warning": (
                            f"IP {ip} is within NAT subnet {subnet} but will NOT be "
                            f"reachable from outside. For external access use bridge mode or IPAM port-forward."
                        ),
                        "gateway": info["gateway"],
                        "mode":    "NAT",
                    }
                else:
                    return {
                        "valid":  False,
                        "reason": f"IP {ip} is outside NAT subnet {subnet}. VM won't have connectivity.",
                        "mode":   "NAT",
                    }
            except Exception:
                pass
        return {
            "valid":   True,
            "warning": "NAT mode â€” static IP works internally but not reachable from outside.",
            "mode":    "NAT",
        }

    if mode == "BRIDGE":
        return {
            "valid":   True,
            "gateway": info.get("gateway", ""),
            "mode":    "BRIDGE",
            "note":    f"Set gateway to your upstream router, subnet to match {info.get('subnet','?')}",
        }

    return {"valid": False, "reason": f"Cannot validate static IP in mode: {mode}"}


def suggest_ip_fix(vm_id: str) -> dict:
    """Return human-readable recommendation for IP setup."""
    info  = get_network_info(vm_id)
    mode  = info["mode"]
    steps = []

    if mode == "NAT":
        steps = [
            "OPTION A â€” Bridge mode (recommended for real upstream IP):",
            "  1. Run: sudo bash /opt/ankavm/scripts/setup-bridge.sh",
            "  2. Edit VM network in ankavm UI â†’ change to 'oxbridge'",
            "  3. Inside VM: set IP on upstream subnet, gateway = upstream router",
            "",
            "OPTION B â€” Static IP within NAT (no external access):",
            f"  1. Inside VM: set IP in {info.get('subnet', '192.168.122.0/24')}",
            f"  2. Gateway: {info.get('gateway', '192.168.122.1')}",
            "  3. VM can reach internet via NAT but is NOT reachable from outside",
            "",
            "OPTION C â€” Port forwarding (access specific ports):",
            "  ankavm UI â†’ Network â†’ IPAM â†’ Assign IP â†’ creates DNAT rule",
        ]
    elif mode == "BRIDGE":
        steps = [
            "VM is in BRIDGE mode â€” static IPs work natively.",
            "Inside VM:",
            "  1. Set IP on same subnet as host",
            "  2. Set gateway = upstream router (not the host IP)",
            "  3. DNS: 8.8.8.8 or your local DNS",
        ]
    else:
        steps = [f"Current mode: {mode}", info.get("guidance", "")]

    return {
        "vm_id":   vm_id,
        "mode":    mode,
        "steps":   steps,
        "guidance": info.get("guidance", ""),
    }


def list_routable_networks() -> list[dict]:
    """List libvirt networks where VMs can get real upstream IPs (bridge/direct mode)."""
    ok, out = _run(["virsh", "net-list", "--all"])
    if not ok:
        return []

    networks = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or parts[0] in ("Name", "---"):
            continue
        name = parts[0]
        info = _get_libvirt_network_info(name)
        fwd  = info.get("forward_mode", "isolated")
        networks.append({
            "name":         name,
            "forward_mode": fwd,
            "routable":     fwd in ("bridge", "route", "open", "direct"),
            "nat":          fwd == "nat",
            "subnet":       info.get("subnet", ""),
            "gateway":      info.get("gateway", ""),
        })
    return networks


def get_bridge_setup_status() -> dict:
    """Check if oxbr0 bridge is configured."""
    ok, out = _run(["ip", "link", "show", "oxbr0"])
    bridge_exists = ok and "oxbr0" in out

    if bridge_exists:
        _, ip_out = _run(["ip", "addr", "show", "oxbr0"])
        ip_match  = re.search(r"inet\s+(\S+)", ip_out)
        bridge_ip = ip_match.group(1) if ip_match else ""
        return {
            "configured": True,
            "bridge_name": "oxbr0",
            "ip": bridge_ip,
            "message": f"oxbr0 is configured ({bridge_ip}). VMs can use real upstream IPs.",
        }
    return {
        "configured": False,
        "bridge_name": "oxbr0",
        "ip": "",
        "message": (
            "oxbr0 bridge not found. VMs are in NAT mode by default. "
            "To enable bridge networking: sudo bash /opt/ankavm/scripts/setup-bridge.sh"
        ),
        "setup_command": "sudo bash /opt/ankavm/scripts/setup-bridge.sh",
    }






