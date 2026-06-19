"""
ankavm Disk Encryption â€” Live VM disk LUKS
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
qemu-img + cryptsetup ile VM disklerini AES-XTS-512 ile ÅŸifrele.
Key file: /etc/ankavm/disk_keys/<vm_id>.key (perm 0600, root-only)

LUKS2 header'lÄ± raw/qcow2 disk Ã¼retir. VM XML'de:
  <encryption format="luks">
    <secret type="passphrase" uuid="..."/>
  </encryption>
"""
from __future__ import annotations
import os, json, logging, subprocess, secrets, uuid, time
from pathlib import Path

log = logging.getLogger("disk_encryption")
_KEY_DIR  = Path("/etc/ankavm/disk_keys")
_REG      = Path("/var/lib/ankavm/disk_encryption.json")
_LIBVIRT_SECRETS = Path("/etc/libvirt/secrets")


def _load() -> dict:
    try:
        return json.loads(_REG.read_text(encoding="utf-8")) if _REG.exists() else {"disks": {}}
    except Exception:
        return {"disks": {}}


def _save(d: dict):
    _REG.parent.mkdir(parents=True, exist_ok=True)
    _REG.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _gen_passphrase(bits: int = 256) -> str:
    return secrets.token_urlsafe(bits // 8)


def encrypt_disk(disk_path: str, vm_id: str, passphrase: str = None) -> dict:
    """Wrap raw disk with LUKS2 header. WARNING â€” destructive without backup."""
    if not os.path.exists(disk_path):
        return {"ok": False, "error": "disk not found"}
    _KEY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

    pp = passphrase or _gen_passphrase()
    key_file = _KEY_DIR / f"{vm_id}.key"
    key_file.write_text(pp, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except Exception:
        pass

    secret_uuid = str(uuid.uuid4())
    try:
        # qemu-img convert: raw â†’ luks
        encrypted_path = disk_path + ".luks"
        r = subprocess.run([
            "qemu-img", "convert", "-O", "luks",
            "--object", f"secret,id=sec0,format=raw,file={key_file}",
            "-o", "key-secret=sec0,cipher-alg=aes-256,cipher-mode=xts,hash-alg=sha256,iter-time=2000",
            disk_path, encrypted_path
        ], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "error": f"qemu-img: {r.stderr.strip()}"}

        d = _load()
        d.setdefault("disks", {})[vm_id] = {
            "path":        encrypted_path,
            "secret_uuid": secret_uuid,
            "key_file":    str(key_file),
            "encrypted_at": int(time.time()),
            "algorithm":   "aes-xts-256",
        }
        _save(d)
        log.info("disk encrypted: %s â†’ %s", disk_path, encrypted_path)
        return {"ok": True, "path": encrypted_path, "secret_uuid": secret_uuid}
    except FileNotFoundError:
        return {"ok": False, "error": "qemu-img not installed"}
    except Exception as e:
        log.error("encrypt_disk: %s", e)
        return {"ok": False, "error": str(e)}


def list_encrypted_disks() -> list:
    return [{"vm_id": k, **v} for k, v in _load().get("disks", {}).items()]


def get_status(vm_id: str) -> dict:
    return _load().get("disks", {}).get(vm_id, {"encrypted": False})


def rotate_key(vm_id: str) -> dict:
    """Add new LUKS slot with new key + remove old slot."""
    d = _load().get("disks", {}).get(vm_id)
    if not d:
        return {"ok": False, "error": "vm not encrypted"}
    new_pp = _gen_passphrase()
    new_key = _KEY_DIR / f"{vm_id}.key.new"
    new_key.write_text(new_pp)
    try:
        # cryptsetup luksAddKey path --key-file=old_key
        r = subprocess.run([
            "cryptsetup", "luksAddKey", d["path"],
            "--key-file", d["key_file"], str(new_key)
        ], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()}
        # Replace key file
        new_key.replace(Path(d["key_file"]))
        return {"ok": True, "rotated_at": int(time.time())}
    except Exception as e:
        return {"ok": False, "error": str(e)}






