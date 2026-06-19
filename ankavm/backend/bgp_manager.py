"""
bgp_manager.py â€” BGP tÃ¼nelleme yÃ¶netimi (FRRouting / BIRD)
ankavm Hypervisor backend module

Gereksinimler:
  - FRRouting: apt install frr frr-pythontools
    veya
  - BIRD: apt install bird2

Desteklenen iÅŸlemler:
  - BGP peer ekleme/silme/listeleme
  - Route redistribution
  - Oturum durumu sorgulama (vtysh)
  - Announce prefix
"""

import subprocess
import json
import logging
import os
import re
import shutil
import threading

log = logging.getLogger("ankavm.bgp")

FRR_CONF    = "/etc/frr/frr.conf"
FRR_DAEMON  = "/etc/frr/daemons"
BGP_DB_FILE = "/var/lib/ankavm/bgp_peers.json"
_lock       = threading.Lock()


# â”€â”€ Backend detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_backend() -> str:
    """FRRouting veya BIRD kurulu mu? 'frr' | 'bird' | 'none' dÃ¶ner."""
    if shutil.which("vtysh"):
        return "frr"
    if shutil.which("birdc"):
        return "bird"
    return "none"


BACKEND = detect_backend()


# â”€â”€ YardÄ±mcÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _vtysh(*commands: str, timeout: int = 10) -> tuple:
    """
    vtysh Ã¼zerinden FRR komutlarÄ± Ã§alÄ±ÅŸtÄ±r.
    DÃ¶ner: (stdout, stderr, returncode)
    """
    cmd_args = ["vtysh"]
    for c in commands:
        cmd_args += ["-c", c]
    try:
        r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e:
        return "", str(e), -1


def _birdc(command: str, timeout: int = 10) -> tuple:
    """birdc Ã¼zerinden BIRD komutu Ã§alÄ±ÅŸtÄ±r."""
    try:
        r = subprocess.run(
            ["birdc", command], capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e:
        return "", str(e), -1


def _load_db() -> dict:
    try:
        if os.path.exists(BGP_DB_FILE):
            with open(BGP_DB_FILE) as f:
                return json.load(f)
    except Exception as e:
        log.warning("BGP DB yÃ¼kleme hatasÄ±: %s", e)
    return {"peers": {}}


def _save_db(data: dict):
    try:
        os.makedirs(os.path.dirname(BGP_DB_FILE), exist_ok=True)
        tmp = BGP_DB_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, BGP_DB_FILE)
    except Exception as e:
        log.error("BGP DB kaydetme hatasÄ±: %s", e)


# â”€â”€ Peer yÃ¶netimi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def add_peer(peer_ip: str, peer_asn: int, local_asn: int,
             description: str = "", password: str = "",
             multihop: int = 1, soft_reconfig: bool = True) -> dict:
    """
    BGP peer ekle (FRRouting vtysh).
    DÃ¶ner: {success, message}
    """
    if BACKEND != "frr":
        return {"success": False, "message": f"FRRouting kurulu deÄŸil (backend={BACKEND})"}
    if not re.match(r"^[d.]+$|^[a-fA-F0-9:]+$", peer_ip):
        return {"success": False, "message": "GeÃ§ersiz peer IP"}

    # rapor #74 fix: sanitize free-text fields before injecting into vtysh
    try:
        description = _sanitize_bgp_str(description, "description", max_len=64)
        password    = _sanitize_bgp_str(password, "password", max_len=128)
    except ValueError as e:
        return {"success": False, "message": str(e)}


    sr_cmd = f"  neighbor {peer_ip} soft-reconfiguration inbound" if soft_reconfig else ""
    mh_cmd = f"  neighbor {peer_ip} ebgp-multihop {multihop}" if multihop > 1 else ""
    pw_cmd = f"  neighbor {peer_ip} password {password}" if password else ""
    desc_cmd = f"  neighbor {peer_ip} description {description}" if description else ""

    cmds = [
        "configure terminal",
        f"router bgp {local_asn}",
        f"  neighbor {peer_ip} remote-as {peer_asn}",
    ]
    for extra in [desc_cmd, pw_cmd, mh_cmd, sr_cmd]:
        if extra:
            cmds.append(extra)
    cmds += ["  exit", "exit", "write memory"]

    stdout, stderr, rc = _vtysh(*cmds)
    if rc == 0:
        with _lock:
            db = _load_db()
            db["peers"][peer_ip] = {
                "peer_ip":    peer_ip,
                "peer_asn":   peer_asn,
                "local_asn":  local_asn,
                "description": description,
                "multihop":   multihop,
                "soft_reconfig": soft_reconfig,
                "has_password": bool(password),
            }
            _save_db(db)
        log.info("BGP peer eklendi: %s AS%d", peer_ip, peer_asn)
        return {"success": True, "message": f"Peer {peer_ip} (AS{peer_asn}) eklendi"}
    else:
        log.error("BGP peer ekleme hatasÄ±: %s", stderr or stdout)
        return {"success": False, "message": stderr or stdout or "vtysh hatasÄ±"}


def remove_peer(peer_ip: str, local_asn: int) -> dict:
    """BGP peer kaldÄ±r."""
    if BACKEND != "frr":
        return {"success": False, "message": "FRRouting kurulu deÄŸil"}

    stdout, stderr, rc = _vtysh(
        "configure terminal",
        f"router bgp {local_asn}",
        f"  no neighbor {peer_ip}",
        "  exit", "exit", "write memory"
    )
    if rc == 0:
        with _lock:
            db = _load_db()
            db["peers"].pop(peer_ip, None)
            _save_db(db)
        log.info("BGP peer kaldÄ±rÄ±ldÄ±: %s", peer_ip)
        return {"success": True, "message": f"Peer {peer_ip} kaldÄ±rÄ±ldÄ±"}
    return {"success": False, "message": stderr or stdout}


def list_peers() -> list:
    """KayÄ±tlÄ± peer'larÄ± DB'den dÃ¶ndÃ¼r."""
    with _lock:
        db = _load_db()
    return list(db.get("peers", {}).values())


def get_peer_status(peer_ip: str = None) -> list:
    """
    FRRouting'den BGP oturum durumu al.
    peer_ip: None ise tÃ¼m peer'lar.
    """
    if BACKEND == "frr":
        cmd = f"show bgp neighbors {peer_ip} json" if peer_ip else "show bgp summary json"
        stdout, stderr, rc = _vtysh(cmd)
        if rc != 0:
            return [{"error": stderr or "vtysh hatasÄ±"}]
        try:
            data = json.loads(stdout)
            # Normalize: summary â†’ list of {peer, state, uptime, prefixes}
            if "peers" in data:
                return [
                    {
                        "peer":     p,
                        "state":    info.get("bgpState", "Unknown"),
                        "uptime":   info.get("bgpTimerUp", 0),
                        "prefixes": info.get("prefixReceivedCount", 0),
                        "asn":      info.get("remoteAs"),
                    }
                    for p, info in data["peers"].items()
                ]
            return [data]
        except json.JSONDecodeError:
            return [{"raw": stdout}]
    elif BACKEND == "bird":
        stdout, _, _ = _birdc("show protocols all")
        return [{"raw": stdout}]
    return []


def announce_prefix(prefix: str, local_asn: int, next_hop: str = "self") -> dict:
    """
    BGP prefix announce et (network komutu ile).
    prefix: "192.0.2.0/24"
    """
    if BACKEND != "frr":
        return {"success": False, "message": "FRRouting kurulu deÄŸil"}
    if not re.match(r"^[\d\.]+/\d+$|^[a-fA-F0-9:]+/\d+$", prefix):
        return {"success": False, "message": "GeÃ§ersiz prefix"}
    # rapor #74 fix: validate prefix length range (IPv4: 0-32, IPv6: 0-128)
    if not _validate_prefix_len(prefix):
        return {"success": False, "message": "GeÃ§ersiz prefix uzunluÄŸu (IPv4: /0-32, IPv6: /0-128)"}

    stdout, stderr, rc = _vtysh(
        "configure terminal",
        f"router bgp {local_asn}",
        f"  network {prefix}",
        "  exit", "exit", "write memory"
    )
    if rc == 0:
        return {"success": True, "message": f"Prefix {prefix} announce edildi"}
    return {"success": False, "message": stderr or stdout}


def withdraw_prefix(prefix: str, local_asn: int) -> dict:
    """BGP prefix withdraw et."""
    if BACKEND != "frr":
        return {"success": False, "message": "FRRouting kurulu deÄŸil"}

    stdout, stderr, rc = _vtysh(
        "configure terminal",
        f"router bgp {local_asn}",
        f"  no network {prefix}",
        "  exit", "exit", "write memory"
    )
    if rc == 0:
        return {"success": True, "message": f"Prefix {prefix} withdraw edildi"}
    return {"success": False, "message": stderr or stdout}


def get_routes(address_family: str = "ipv4") -> list:
    """BGP route tablosunu al."""
    if BACKEND == "frr":
        cmd = f"show bgp {address_family} unicast json"
        stdout, _, rc = _vtysh(cmd)
        if rc != 0:
            return []
        try:
            data = json.loads(stdout)
            routes = data.get("routes", {})
            return [
                {"prefix": pfx, "paths": info}
                for pfx, info in routes.items()
            ]
        except Exception:
            return [{"raw": stdout}]
    return []


def get_full_status() -> dict:
    """BGP genel durum Ã¶zeti."""
    return {
        "backend":  BACKEND,
        "available": BACKEND != "none",
        "peers":    list_peers(),
        "sessions": get_peer_status() if BACKEND != "none" else [],
    }


# â”€â”€ rapor #74 fix: vtysh injection sanitization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _sanitize_bgp_str(value: str, field: str = "value", max_len: int = 64) -> str:
    """
    BGP description/password â€” newline, semicolon, vtysh metachar yasak.
    YalnÄ±zca yazdÄ±rÄ±labilir ASCII karakterlere izin ver.
    """
    if not value:
        return value
    value = str(value)[:max_len]
    # Newline, NULL, vtysh komut ayÄ±rÄ±cÄ±larÄ±
    if re.search(r'[\r\n\x00;`$|&]', value):
        raise ValueError(f"BGP {field}: geÃ§ersiz karakter iÃ§eriyor")
    # YalnÄ±zca yazdÄ±rÄ±labilir ASCII
    if not re.match(r'^[\x20-\x7E]+$', value):
        raise ValueError(f"BGP {field}: yalnÄ±zca ASCII karakterlere izin verilir")
    return value


def _validate_prefix_len(prefix: str) -> bool:
    """Prefix length realistik mi? IPv4: /0-32, IPv6: /0-128"""
    try:
        net, length_str = prefix.rsplit("/", 1)
        length = int(length_str)
        if ":" in net:  # IPv6
            return 0 <= length <= 128
        else:            # IPv4
            return 0 <= length <= 32
    except Exception:
        return False






