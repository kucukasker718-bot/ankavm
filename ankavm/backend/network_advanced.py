"""
ankavm Network Advanced — VXLAN, IPv6, BFD, DDoS mitigation
─────────────────────────────────────────────────────────────
SDN overlay + IPv6 dual-stack + failure detection + rate limit.

API:
    vxlan_create/list/delete
    ipv6_status/configure
    bfd_status
    ddos_apply_rules
"""

import subprocess, json, logging
from pathlib import Path

log = logging.getLogger("network_advanced")
_VXLAN_STORE = Path("/var/lib/ankavm/vxlans.json")
_DDOS_CFG    = Path("/var/lib/ankavm/ddos_config.json")


# ── VXLAN ───────────────────────────────────────────────────────────────────
def vxlan_list() -> list:
    if not _VXLAN_STORE.exists():
        return []
    try:
        return json.loads(_VXLAN_STORE.read_text())
    except Exception:
        return []


def _save_vxlans(items):
    _VXLAN_STORE.parent.mkdir(parents=True, exist_ok=True)
    _VXLAN_STORE.write_text(json.dumps(items, indent=2))


def vxlan_create(name: str, vni: int, group: str = "239.1.1.1",
                  dev: str = "eth0", mtu: int = 1450) -> dict:
    """ip link add vxlan."""
    try:
        cmd = ["ip", "link", "add", name, "type", "vxlan",
               "id", str(vni), "group", group, "dev", dev,
               "dstport", "4789"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()}
        subprocess.run(["ip", "link", "set", name, "mtu", str(mtu)],
                       capture_output=True, timeout=5)
        subprocess.run(["ip", "link", "set", name, "up"],
                       capture_output=True, timeout=5)

        items = vxlan_list()
        items.append({"name": name, "vni": vni, "group": group, "dev": dev,
                      "mtu": mtu, "created_at": int(__import__("time").time())})
        _save_vxlans(items)
        return {"ok": True, "name": name, "vni": vni}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def vxlan_delete(name: str) -> dict:
    try:
        subprocess.run(["ip", "link", "del", name],
                       capture_output=True, timeout=5)
        items = [v for v in vxlan_list() if v["name"] != name]
        _save_vxlans(items)
        return {"ok": True, "name": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── IPv6 dual-stack ─────────────────────────────────────────────────────────
def ipv6_status() -> dict:
    try:
        r = subprocess.run(["ip", "-6", "addr"], capture_output=True, text=True, timeout=5)
        import re
        addrs = re.findall(r"inet6 ([\da-f:]+/\d+) scope (\S+)", r.stdout)
        return {
            "enabled":   True,
            "addresses": [{"addr": a, "scope": s} for a, s in addrs],
            "count":     len(addrs),
        }
    except Exception as e:
        return {"enabled": False, "error": str(e)}


def ipv6_configure(enable: bool) -> dict:
    """sysctl ile IPv6 toggle."""
    try:
        val = "0" if enable else "1"  # disable_ipv6=0 means enabled
        for key in ["net.ipv6.conf.all.disable_ipv6",
                    "net.ipv6.conf.default.disable_ipv6"]:
            subprocess.run(["sysctl", "-w", f"{key}={val}"],
                           capture_output=True, timeout=5)
        Path("/etc/sysctl.d/99-ankavm-ipv6.conf").write_text(
            f"net.ipv6.conf.all.disable_ipv6 = {val}\n"
            f"net.ipv6.conf.default.disable_ipv6 = {val}\n"
        )
        return {"ok": True, "enabled": enable}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── BFD (Bidirectional Forwarding Detection) - basic ping monitor ──────────
def bfd_status() -> dict:
    """OVS bfd: ovs-vsctl get interface ... bfd"""
    try:
        r = subprocess.run(["which", "ovs-vsctl"], capture_output=True, timeout=3)
        if r.returncode != 0:
            return {"available": False, "error": "OVS yok"}
        # List interfaces with bfd
        r2 = subprocess.run(["ovs-vsctl", "list", "interface"],
                            capture_output=True, text=True, timeout=10)
        bfd_count = r2.stdout.count("bfd")
        return {"available": True, "bfd_enabled_interfaces": bfd_count}
    except Exception as e:
        return {"available": False, "error": str(e)}


def bfd_enable(iface: str, remote: str) -> dict:
    """OVS interface'inde BFD aktif et."""
    try:
        r = subprocess.run([
            "ovs-vsctl", "set", "interface", iface,
            f"bfd:enable=true",
            f"bfd:min_rx=300",
            f"bfd:min_tx=300",
        ], capture_output=True, text=True, timeout=10)
        return {"ok": r.returncode == 0, "iface": iface, "remote": remote,
                "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── DDoS Mitigation (iptables rate limit) ───────────────────────────────────
def ddos_get_config() -> dict:
    if _DDOS_CFG.exists():
        try: return json.loads(_DDOS_CFG.read_text())
        except: pass
    return {
        "enabled":       False,
        "syn_per_sec":   100,
        "icmp_per_sec":  10,
        "udp_per_sec":   500,
        "conn_per_ip":   100,
    }


def ddos_apply(config: dict) -> dict:
    """iptables ile temel DDoS mitigation."""
    cfg = {**ddos_get_config(), **(config or {})}

    rules = []
    if cfg.get("enabled"):
        rules = [
            # SYN flood
            ["iptables", "-N", "ankavm_SYN_FLOOD"],
            ["iptables", "-A", "INPUT", "-p", "tcp", "--syn", "-j", "ankavm_SYN_FLOOD"],
            ["iptables", "-A", "ankavm_SYN_FLOOD", "-m", "limit",
             "--limit", f"{cfg['syn_per_sec']}/s", "--limit-burst", "200",
             "-j", "RETURN"],
            ["iptables", "-A", "ankavm_SYN_FLOOD", "-j", "DROP"],
            # ICMP flood
            ["iptables", "-A", "INPUT", "-p", "icmp", "-m", "limit",
             "--limit", f"{cfg['icmp_per_sec']}/s", "-j", "ACCEPT"],
            ["iptables", "-A", "INPUT", "-p", "icmp", "-j", "DROP"],
            # Connection limit per IP
            ["iptables", "-A", "INPUT", "-p", "tcp", "-m", "connlimit",
             "--connlimit-above", str(cfg['conn_per_ip']), "-j", "REJECT"],
        ]

    applied = []
    for r in rules:
        try:
            res = subprocess.run(r, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                applied.append(" ".join(r))
        except Exception as e:
            log.debug("DDoS rule fail: %s", e)

    _DDOS_CFG.parent.mkdir(parents=True, exist_ok=True)
    _DDOS_CFG.write_text(json.dumps(cfg, indent=2))
    return {"ok": True, "applied_rules": len(applied), "config": cfg}


def ddos_clear() -> dict:
    """ankavm DDoS kurallarını temizle."""
    try:
        subprocess.run(["iptables", "-F", "ankavm_SYN_FLOOD"],
                       capture_output=True, timeout=5)
        subprocess.run(["iptables", "-X", "ankavm_SYN_FLOOD"],
                       capture_output=True, timeout=5)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}






