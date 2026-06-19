"""
ankavm Ã‡ok KullanÄ±cÄ± YÃ¶netim ModÃ¼lÃ¼
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
KullanÄ±cÄ±lar /var/lib/ankavm/users.json dosyasÄ±nda saklanÄ±r.
Admin (tek kullanÄ±cÄ±) credentials.py ile yÃ¶netilir.
Ek kullanÄ±cÄ±lar bu modÃ¼l ile eklenir.
"""

import os
import json
import time
import secrets
import hashlib
import config

USERS_FILE = os.path.join(config.DATA_DIR, "users.json")


def _load() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(USERS_FILE, 0o600)


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
        new_h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
        return secrets.compare_digest(h, new_h.hex())
    except Exception:
        return False


def list_users() -> list:
    """TÃ¼m kullanÄ±cÄ±larÄ± dÃ¶ndÃ¼r (password_hash hariÃ§)."""
    data = _load()
    users = []
    for username, info in data.get("users", {}).items():
        users.append({
            "username": username,
            "role": info.get("role", "viewer"),
            "created": info.get("created"),
            "last_login": info.get("last_login"),
        })
    return users


def add_user(username: str, password: str, role: str = "viewer") -> dict:
    """Yeni kullanÄ±cÄ± ekle."""
    if not username or len(username) < 2:
        raise ValueError("KullanÄ±cÄ± adÄ± en az 2 karakter olmalÄ±")
    if len(password) < 8:
        raise ValueError("Åifre en az 8 karakter olmalÄ±")
    valid_roles = {"viewer", "operator", "administrator", "vm-user"}
    if role not in valid_roles:
        raise ValueError(f"GeÃ§ersiz rol. Kabul edilenler: {', '.join(valid_roles)}")

    data = _load()
    if "users" not in data:
        data["users"] = {}
    if username in data["users"]:
        raise ValueError(f"KullanÄ±cÄ± zaten mevcut: {username}")

    data["users"][username] = {
        "password_hash": _hash_password(password),
        "role": role,
        "created": time.time(),
    }
    _save(data)
    return {"username": username, "role": role, "created": data["users"][username]["created"]}


def delete_user(username: str):
    """KullanÄ±cÄ± sil."""
    data = _load()
    if username not in data.get("users", {}):
        raise KeyError(f"KullanÄ±cÄ± bulunamadÄ±: {username}")
    del data["users"][username]
    _save(data)


def update_user_role(username: str, role: str):
    """KullanÄ±cÄ± rolÃ¼nÃ¼ gÃ¼ncelle."""
    valid_roles = {"viewer", "operator", "administrator", "vm-user"}
    if role not in valid_roles:
        raise ValueError(f"GeÃ§ersiz rol: {role}")
    data = _load()
    if username not in data.get("users", {}):
        raise KeyError(f"KullanÄ±cÄ± bulunamadÄ±: {username}")
    data["users"][username]["role"] = role
    _save(data)


def update_user(username: str, new_username: str = None, new_password: str = None, new_role: str = None):
    """KullanÄ±cÄ± gÃ¼ncelle (kullanÄ±cÄ± adÄ±, ÅŸifre, rol)."""
    data = _load()
    if username not in data.get("users", {}):
        raise KeyError(f"KullanÄ±cÄ± bulunamadÄ±: {username}")

    user_data = data["users"][username]

    if new_password:
        if len(new_password) < 8:
            raise ValueError("Åifre en az 8 karakter olmalÄ±")
        user_data["password_hash"] = _hash_password(new_password)

    if new_role:
        valid_roles = {"viewer", "operator", "administrator", "vm-user"}
        if new_role not in valid_roles:
            raise ValueError(f"GeÃ§ersiz rol: {new_role}")
        user_data["role"] = new_role

    if new_username and new_username != username:
        if len(new_username) < 2:
            raise ValueError("KullanÄ±cÄ± adÄ± en az 2 karakter olmalÄ±")
        if new_username in data["users"]:
            raise ValueError(f"KullanÄ±cÄ± adÄ± zaten mevcut: {new_username}")
        data["users"][new_username] = user_data
        del data["users"][username]
    else:
        data["users"][username] = user_data

    _save(data)


def verify_user(username: str, password: str) -> bool:
    """KullanÄ±cÄ± ÅŸifresini doÄŸrula."""
    data = _load()
    user = data.get("users", {}).get(username)
    if not user:
        return False
    return _verify_password(password, user.get("password_hash", ""))


def get_user_role(username: str) -> str:
    """KullanÄ±cÄ±nÄ±n rolÃ¼nÃ¼ dÃ¶ndÃ¼r."""
    data = _load()
    user = data.get("users", {}).get(username)
    return user.get("role", "viewer") if user else "viewer"


# â”€â”€ VM Assignment (for vm-user role) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

VM_ASSIGN_FILE = os.path.join(config.DATA_DIR, "vm_assignments.json")


def _load_assignments() -> dict:
    """Load vm assignments: {username: [vm_id, ...]}"""
    if os.path.exists(VM_ASSIGN_FILE):
        try:
            with open(VM_ASSIGN_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_assignments(data: dict):
    os.makedirs(os.path.dirname(VM_ASSIGN_FILE), exist_ok=True)
    with open(VM_ASSIGN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(VM_ASSIGN_FILE, 0o600)


def get_user_vms(username: str) -> list:
    """Return list of vm_ids assigned to username."""
    data = _load_assignments()
    return data.get(username, [])


def assign_vm(username: str, vm_id: str):
    """Assign vm_id to username. Idempotent."""
    data = _load_assignments()
    if username not in data:
        data[username] = []
    if vm_id not in data[username]:
        data[username].append(vm_id)
    _save_assignments(data)


def unassign_vm(username: str, vm_id: str):
    """Remove vm_id from username assignments."""
    data = _load_assignments()
    if username in data:
        data[username] = [v for v in data[username] if v != vm_id]
        if not data[username]:
            del data[username]
    _save_assignments(data)


def get_vm_users(vm_id: str) -> list:
    """Return list of usernames assigned to vm_id."""
    data = _load_assignments()
    return [uname for uname, vms in data.items() if vm_id in vms]


def unassign_all_user_vms(username: str):
    """Remove all VM assignments for username (call when deleting user)."""
    data = _load_assignments()
    if username in data:
        del data[username]
    _save_assignments(data)






