"""
ankavm Network I/O Control (NIOC)
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
VM baÅŸÄ± bant garantisi ve sÄ±nÄ±rÄ± (tc + libvirt QoS).

API:
    set_vm_bandwidth(vm_id, inbound_kbps, outbound_kbps, burst_kbps) -> dict
    get_vm_bandwidth(vm_id) -> dict
    remove_vm_bandwidth(vm_id) -> bool
    list_profiles() / create_profile() / apply_profile_to_vm()
"""

import os, json, subprocess, logging, re
from pathlib import Path

log = logging.getLogger("nioc_manager")
_PROFILES = Path("/var/lib/ankavm/nioc_profiles.json")


_DEFAULT_PROFILES = [
    {"name": "low",        "in_kbps": 1024,    "out_kbps": 1024,   "burst": 256},     # 1 Mbps
    {"name": "normal",     "in_kbps": 10240,   "out_kbps": 10240,  "burst": 2048},    # 10 Mbps
    {"name": "high",       "in_kbps": 102400,  "out_kbps": 102400, "burst": 10240},   # 100 Mbps
    {"name": "unlimited",  "in_kbps": 0,       "out_kbps": 0,      "burst": 0},
]


def _load_profiles() -> list:
    if _PROFILES.exists():
        try:
            return json.loads(_PROFILES.read_text())
        except Exception:
            pass
    return list(_DEFAULT_PROFILES)


def _save_profiles(profiles: list):
    _PROFILES.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES.write_text(json.dumps(profiles, indent=2, ensure_ascii=False))


def list_profiles() -> list:
    return _load_profiles()


def create_profile(name: str, in_kbps: int, out_kbps: int, burst: int = 1024) -> dict:
    profiles = _load_profiles()
    if any(p["name"] == name for p in profiles):
        raise ValueError(f"Profile zaten var: {name}")
    p = {"name": name, "in_kbps": in_kbps, "out_kbps": out_kbps, "burst": burst}
    profiles.append(p)
    _save_profiles(profiles)
    return p


def delete_profile(name: str) -> bool:
    profiles = _load_profiles()
    new = [p for p in profiles if p["name"] != name]
    if len(new) == len(profiles):
        return False
    _save_profiles(new)
    return True


def set_vm_bandwidth(vm_id: str, in_kbps: int = 0, out_kbps: int = 0,
                      burst_kbps: int = 1024) -> dict:
    """
    virsh domiftune ile bant ayarÄ±.
    in/out = average kbps (1000 bps), 0 = sÄ±nÄ±rsÄ±z.
    """
    # Get first interface
    try:
        r = subprocess.run(["virsh", "domiflist", vm_id],
                           capture_output=True, text=True, timeout=10)
        lines = r.stdout.strip().split("\n")
        if len(lines) < 3:
            return {"ok": False, "error": "VM aÄŸ arabirimi yok"}
        # Skip header (2 lines), pick first interface name
        iface = lines[2].split()[0]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    args = ["virsh", "domiftune", vm_id, iface]
    if in_kbps > 0:
        args += ["--inbound", f"{in_kbps},{burst_kbps},{burst_kbps}"]
    else:
        args += ["--inbound", "0,0,0"]   # 0 = sÄ±nÄ±rsÄ±z
    if out_kbps > 0:
        args += ["--outbound", f"{out_kbps},{burst_kbps},{burst_kbps}"]
    else:
        args += ["--outbound", "0,0,0"]
    args += ["--live", "--config"]

    r = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip()}
    return {
        "ok":       True,
        "vm_id":    vm_id,
        "iface":    iface,
        "in_kbps":  in_kbps,
        "out_kbps": out_kbps,
        "burst":    burst_kbps,
    }


def get_vm_bandwidth(vm_id: str) -> dict:
    try:
        r = subprocess.run(["virsh", "domiflist", vm_id],
                           capture_output=True, text=True, timeout=10)
        ifaces = []
        for line in r.stdout.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 1:
                ifaces.append(parts[0])
        if not ifaces:
            return {"vm_id": vm_id, "interfaces": []}

        result = {"vm_id": vm_id, "interfaces": []}
        for iface in ifaces:
            r2 = subprocess.run(["virsh", "domiftune", vm_id, iface],
                                capture_output=True, text=True, timeout=10)
            entry = {"iface": iface}
            for line in r2.stdout.splitlines():
                m = re.match(r"(\S+)\s*:\s*(\S+)", line.strip())
                if m:
                    entry[m.group(1)] = m.group(2)
            result["interfaces"].append(entry)
        return result
    except Exception as e:
        return {"vm_id": vm_id, "error": str(e)}


def apply_profile_to_vm(vm_id: str, profile_name: str) -> dict:
    p = next((p for p in _load_profiles() if p["name"] == profile_name), None)
    if not p:
        raise KeyError(f"Profil bulunamadÄ±: {profile_name}")
    return set_vm_bandwidth(vm_id, p["in_kbps"], p["out_kbps"], p.get("burst", 1024))


def remove_vm_bandwidth(vm_id: str) -> dict:
    """SÄ±nÄ±rÄ± kaldÄ±r (0,0,0 = unlimited)."""
    return set_vm_bandwidth(vm_id, 0, 0, 0)






