"""
ankavm Host Profile Manager
Captures and applies host configurations as reusable profiles.
Storage: /var/lib/ankavm/host_profiles.json
"""
import json, uuid, subprocess, logging, threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ankavm.host_profile")
_PROFILES_FILE = Path("/var/lib/ankavm/host_profiles.json")
_lock = threading.Lock()


def _load():
    try:
        if _PROFILES_FILE.exists():
            return json.loads(_PROFILES_FILE.read_text())
    except Exception:
        pass
    return []


def _save(data):
    _PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES_FILE.write_text(json.dumps(data, indent=2))


def _capture_host_config():
    """Capture current host's configuration snapshot."""
    config = {}

    # Kernel sysctl
    try:
        r = subprocess.run(["sysctl", "-a"], capture_output=True, text=True, timeout=5)
        sysctl = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                sysctl[k.strip()] = v.strip()
        config["sysctl"] = {
            k: sysctl[k] for k in [
                "net.ipv4.ip_forward", "vm.swappiness",
                "kernel.shmmax", "net.core.somaxconn",
                "net.ipv4.tcp_fin_timeout",
            ] if k in sysctl
        }
    except Exception:
        config["sysctl"] = {}

    # NTP
    try:
        r = subprocess.run(["timedatectl", "show", "--no-pager"], capture_output=True, text=True, timeout=5)
        ntp = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                ntp[k.strip()] = v.strip()
        config["ntp"] = {
            "NTPSynchronized": ntp.get("NTPSynchronized", ""),
            "NTP": ntp.get("NTP", ""),
            "Timezone": ntp.get("Timezone", ""),
        }
    except Exception:
        config["ntp"] = {}

    # DNS
    try:
        nameservers = []
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    nameservers.append(line.split()[1])
        config["dns"] = {"nameservers": nameservers}
    except Exception:
        config["dns"] = {}

    # SSHD
    try:
        r = subprocess.run(["sshd", "-T"], capture_output=True, text=True, timeout=5)
        ssh = {}
        for line in r.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                ssh[parts[0]] = parts[1]
        config["sshd"] = {k: ssh.get(k, "") for k in
                          ["port", "permitrootlogin", "passwordauthentication", "maxauthtries"]}
    except Exception:
        config["sshd"] = {}

    # CPU governor
    try:
        r = subprocess.run(
            ["cat", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"],
            capture_output=True, text=True
        )
        config["cpu_governor"] = r.stdout.strip()
    except Exception:
        config["cpu_governor"] = "unknown"

    return config


def list_profiles():
    with _lock:
        return _load()


def capture_profile(name, description="", tags=None):
    """Snapshot current host config as a named profile."""
    profile = {
        "id": str(uuid.uuid4()),
        "name": str(name).strip(),
        "description": str(description).strip(),
        "tags": tags or [],
        "config": _capture_host_config(),
        "applied_to": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        profiles = _load()
        profiles.append(profile)
        _save(profiles)
    return profile


def delete_profile(profile_id):
    with _lock:
        profiles = _load()
        new_profiles = [p for p in profiles if p["id"] != profile_id]
        if len(new_profiles) == len(profiles):
            return False
        _save(new_profiles)
    return True


def apply_profile(profile_id, target_host="localhost"):
    """Apply stored sysctl settings from profile to host."""
    with _lock:
        profiles = _load()
        profile = next((p for p in profiles if p["id"] == profile_id), None)

    if not profile:
        return {"ok": False, "error": "Profile not found"}

    applied = []
    errors = []
    sysctl_cfg = profile.get("config", {}).get("sysctl", {})

    for key, value in sysctl_cfg.items():
        try:
            r = subprocess.run(
                ["sysctl", "-w", f"{key}={value}"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                applied.append(key)
            else:
                errors.append(f"{key}: {r.stderr.strip()}")
        except Exception as e:
            errors.append(f"{key}: {str(e)}")

    # Record application
    with _lock:
        profiles = _load()
        for p in profiles:
            if p["id"] == profile_id:
                entry = {"host": target_host, "at": datetime.now(timezone.utc).isoformat()}
                p.setdefault("applied_to", []).append(entry)
                _save(profiles)
                break

    return {"ok": True, "applied": applied, "errors": errors}


def get_profile(profile_id):
    with _lock:
        for p in _load():
            if p["id"] == profile_id:
                return p
    return None






