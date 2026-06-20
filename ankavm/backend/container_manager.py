"""
Container Manager — Docker and LXC container lifecycle management.
"""
import subprocess
import json
import os

# ─── Docker ───────────────────────────────────────────────────────────────────

def docker_available() -> bool:
    r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
    return r.returncode == 0

def list_docker_containers(all_containers: bool = True) -> list:
    """List Docker containers."""
    try:
        args = ["docker", "ps", "--format", "{{json .}}"]
        if all_containers:
            args.insert(2, "-a")
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        result = []
        for line in r.stdout.strip().splitlines():
            if line.strip():
                try:
                    c = json.loads(line)
                    result.append({
                        "id": c.get("ID", ""),
                        "name": c.get("Names", ""),
                        "image": c.get("Image", ""),
                        "status": c.get("Status", ""),
                        "state": c.get("State", ""),
                        "ports": c.get("Ports", ""),
                        "created": c.get("CreatedAt", ""),
                        "type": "docker",
                    })
                except Exception:
                    pass
        return result
    except Exception as e:
        return []

def docker_action(container_id: str, action: str) -> dict:
    """start, stop, restart, pause, unpause, rm a Docker container."""
    valid = {"start", "stop", "restart", "pause", "unpause", "rm"}
    if action not in valid:
        return {"ok": False, "error": f"Invalid action. Valid: {valid}"}
    args = ["docker", action]
    if action == "rm":
        args.append("-f")
    args.append(container_id)
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"ok": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}

def create_docker_container(name: str, image: str, ports: str = "", env: list = None,
                             volumes: str = "", restart: str = "unless-stopped",
                             memory: str = "", cpus: str = "") -> dict:
    """Pull image and create container."""
    args = ["docker", "run", "-d", "--name", name, f"--restart={restart}"]
    if ports:
        for p in ports.split(","):
            p = p.strip()
            if p:
                args += ["-p", p]
    for e in (env or []):
        args += ["-e", e]
    if volumes:
        for v in volumes.split(","):
            v = v.strip()
            if v:
                args += ["-v", v]
    if memory:
        args += ["-m", memory]
    if cpus:
        args += ["--cpus", cpus]
    args.append(image)
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return {"ok": r.returncode == 0, "id": r.stdout.strip(), "stderr": r.stderr.strip()}

def docker_logs(container_id: str, lines: int = 100) -> str:
    r = subprocess.run(["docker", "logs", "--tail", str(lines), container_id],
                       capture_output=True, text=True, timeout=10)
    return r.stdout + r.stderr

def docker_stats_snapshot(container_id: str) -> dict:
    r = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id],
        capture_output=True, text=True, timeout=10
    )
    try:
        return json.loads(r.stdout.strip())
    except Exception:
        return {}

def list_docker_images() -> list:
    r = subprocess.run(
        ["docker", "images", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=10
    )
    result = []
    for line in r.stdout.strip().splitlines():
        try:
            result.append(json.loads(line))
        except Exception:
            pass
    return result

def pull_docker_image(image: str) -> dict:
    r = subprocess.run(["docker", "pull", image], capture_output=True, text=True, timeout=300)
    return {"ok": r.returncode == 0, "output": r.stdout[-2000:], "stderr": r.stderr[-500:]}

# ─── LXC ─────────────────────────────────────────────────────────────────────

def lxc_available() -> bool:
    r = subprocess.run(["which", "lxc-ls"], capture_output=True)
    return r.returncode == 0

def list_lxc_containers() -> list:
    """List LXC containers."""
    try:
        r = subprocess.run(["lxc-ls", "--fancy", "--fancy-format", "name,state,ipv4,autostart"],
                           capture_output=True, text=True, timeout=10)
        result = []
        lines = r.stdout.strip().splitlines()
        for line in lines[2:]:  # skip header
            parts = line.split()
            if len(parts) >= 2:
                result.append({
                    "name": parts[0],
                    "state": parts[1].lower(),
                    "ip": parts[2] if len(parts) > 2 else "",
                    "autostart": parts[3] if len(parts) > 3 else "",
                    "type": "lxc",
                })
        return result
    except Exception:
        return []

def lxc_action(name: str, action: str) -> dict:
    valid = {"start": "lxc-start", "stop": "lxc-stop", "restart": None}
    if action not in valid:
        return {"ok": False, "error": "Invalid action"}
    if action == "restart":
        subprocess.run(["lxc-stop", "-n", name], capture_output=True, timeout=30)
        r = subprocess.run(["lxc-start", "-n", name], capture_output=True, text=True, timeout=30)
    else:
        r = subprocess.run([valid[action], "-n", name], capture_output=True, text=True, timeout=30)
    return {"ok": r.returncode == 0, "stderr": r.stderr.strip()}

def create_lxc_container(name: str, template: str = "ubuntu", release: str = "22.04") -> dict:
    r = subprocess.run(
        ["lxc-create", "-n", name, "-t", "download", "--",
         "--dist", template, "--release", release, "--arch", "amd64"],
        capture_output=True, text=True, timeout=300
    )
    return {"ok": r.returncode == 0, "output": r.stdout[-2000:], "stderr": r.stderr[-500:]}

def destroy_lxc_container(name: str) -> dict:
    subprocess.run(["lxc-stop", "-n", name, "-k"], capture_output=True, timeout=15)
    r = subprocess.run(["lxc-destroy", "-n", name], capture_output=True, text=True, timeout=30)
    return {"ok": r.returncode == 0, "stderr": r.stderr.strip()}






