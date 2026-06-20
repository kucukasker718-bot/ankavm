"""
Cloudflare Tunnel Manager — per-VM cloudflared tunnel management.
Manages tunnel config files and systemd services per VM.
"""
import subprocess
import json
import os
import re
import stat
import yaml

TUNNEL_DIR = "/etc/ankavm/cf-tunnels"
# rapor #58 fix: dizin izinlerini kısıtla (token dosyaları burada)
os.makedirs(TUNNEL_DIR, exist_ok=True)
try:
    os.chmod(TUNNEL_DIR, 0o700)
except Exception:
    pass

# rapor #58 fix: vm_id sanitize — yalnızca UUID benzeri karakterler
_VM_ID_RE = re.compile(r'^[a-zA-Z0-9\-]{1,64}$')

def _sanitize_vm_id(vm_id: str) -> str:
    """Path traversal ve servis adı injection önle."""
    if not vm_id or not _VM_ID_RE.match(vm_id):
        raise ValueError(f"Geçersiz vm_id: {vm_id!r}")
    return vm_id

def _write_secure(path: str, content: str):
    """Dosyayı 0600 izniyle yaz (token/kimlik bilgisi koruma)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)

def cloudflared_available() -> bool:
    r = subprocess.run(["which", "cloudflared"], capture_output=True)
    return r.returncode == 0

def list_tunnels() -> list:
    """List all configured VM tunnels."""
    result = []
    if not os.path.isdir(TUNNEL_DIR):
        return result
    for fname in os.listdir(TUNNEL_DIR):
        if fname.endswith(".json"):
            vm_id = fname[:-5]
            try:
                with open(os.path.join(TUNNEL_DIR, fname)) as f:
                    cfg = json.load(f)
                # Tunnel ID'yi API yanıtından çıkar (hassas bilgi gizle)
                cfg.pop("tunnel_id", None)
                svc = f"ankavm-tunnel-{vm_id}"
                r = subprocess.run(["systemctl", "is-active", svc],
                                   capture_output=True, text=True)
                cfg["status"] = r.stdout.strip()
                cfg["vm_id"] = vm_id
                result.append(cfg)
            except Exception:
                pass
    return result

def create_tunnel(vm_id: str, vm_name: str, hostname: str,
                  target_ip: str, target_port: int, protocol: str = "http") -> dict:
    """
    Create cloudflare tunnel for a VM.
    Requires cloudflared to be already authenticated (cloudflared tunnel login).
    """
    # rapor #58 fix: vm_id sanitize
    try:
        vm_id = _sanitize_vm_id(vm_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if not cloudflared_available():
        return {"ok": False, "error": "cloudflared not installed. Install: curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | apt install cloudflared"}

    tunnel_name = f"ankavm-{vm_id[:8]}"

    # Create tunnel
    r = subprocess.run(
        ["cloudflared", "tunnel", "create", tunnel_name],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0 and "already exists" not in r.stderr:
        return {"ok": False, "error": r.stderr.strip()}

    # Extract tunnel ID from output
    tunnel_id = None
    for line in r.stdout.splitlines():
        if "Created tunnel" in line or "tunnel with id" in line.lower():
            parts = line.split()
            for part in parts:
                if len(part) == 36 and part.count("-") == 4:
                    tunnel_id = part
                    break

    # Write config (YAML — no credentials embedded here)
    config = {
        "tunnel": tunnel_name,
        "credentials-file": f"/root/.cloudflared/{tunnel_id}.json" if tunnel_id else "",
        "ingress": [
            {"hostname": hostname, "service": f"{protocol}://{target_ip}:{target_port}"},
            {"service": "http_status:404"}
        ]
    }

    cfg_path = os.path.join(TUNNEL_DIR, f"{vm_id}.yaml")
    # rapor #58 fix: 0600 perms on config file (contains credentials-file path)
    _write_secure(cfg_path, yaml.dump(config))

    # Save metadata (no tunnel_id in plaintext — only reference)
    meta = {
        "vm_id": vm_id, "vm_name": vm_name, "hostname": hostname,
        "target": f"{target_ip}:{target_port}", "protocol": protocol,
        "tunnel_name": tunnel_name,
        "config_path": cfg_path,
        # tunnel_id intentionally omitted from stored metadata
    }
    meta_path = os.path.join(TUNNEL_DIR, f"{vm_id}.json")
    _write_secure(meta_path, json.dumps(meta, indent=2))

    # Create systemd service
    svc_name = f"ankavm-tunnel-{vm_id}"
    svc_content = f"""[Unit]
Description=ankavm Cloudflare Tunnel - {vm_name}
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --config {cfg_path} run
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""
    svc_path = f"/etc/systemd/system/{svc_name}.service"
    _write_secure(svc_path, svc_content)

    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "enable", svc_name], capture_output=True)
    r2 = subprocess.run(["systemctl", "start", svc_name], capture_output=True, text=True)

    return {"ok": True, "tunnel_name": tunnel_name,
            "hostname": hostname, "service": svc_name}

def delete_tunnel(vm_id: str) -> dict:
    """Stop and remove tunnel for a VM."""
    try:
        vm_id = _sanitize_vm_id(vm_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    svc_name = f"ankavm-tunnel-{vm_id}"
    subprocess.run(["systemctl", "stop", svc_name], capture_output=True)
    subprocess.run(["systemctl", "disable", svc_name], capture_output=True)

    svc_path = f"/etc/systemd/system/{svc_name}.service"
    if os.path.exists(svc_path):
        os.remove(svc_path)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)

    for ext in [".json", ".yaml"]:
        p = os.path.join(TUNNEL_DIR, f"{vm_id}{ext}")
        if os.path.exists(p):
            os.remove(p)

    return {"ok": True, "removed": vm_id}

def tunnel_status(vm_id: str) -> dict:
    try:
        vm_id = _sanitize_vm_id(vm_id)
    except ValueError as e:
        return {"vm_id": vm_id, "error": str(e)}

    svc_name = f"ankavm-tunnel-{vm_id}"
    r = subprocess.run(["systemctl", "is-active", svc_name], capture_output=True, text=True)
    r2 = subprocess.run(["systemctl", "status", svc_name, "--no-pager", "-n", "20"],
                        capture_output=True, text=True)
    return {
        "vm_id": vm_id,
        "active": r.stdout.strip() == "active",
        "status": r.stdout.strip(),
        "log": r2.stdout[-1000:],
    }

def start_tunnel(vm_id: str) -> dict:
    try:
        vm_id = _sanitize_vm_id(vm_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    svc_name = f"ankavm-tunnel-{vm_id}"
    r = subprocess.run(["systemctl", "start", svc_name], capture_output=True, text=True)
    return {"ok": r.returncode == 0, "error": r.stderr.strip()}

def stop_tunnel(vm_id: str) -> dict:
    try:
        vm_id = _sanitize_vm_id(vm_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    svc_name = f"ankavm-tunnel-{vm_id}"
    r = subprocess.run(["systemctl", "stop", svc_name], capture_output=True, text=True)
    return {"ok": r.returncode == 0}






