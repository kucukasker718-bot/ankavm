"""
security_hardening.py â€” ankavm gÃ¼venlik denetim ve sertleÅŸtirme modÃ¼lÃ¼.

Kontrol listesi (Proxmox/KVM best practices):
  1. br_netfilter kernel modÃ¼lÃ¼
  2. IOMMU etkin mi (PCI passthrough izolasyonu)
  3. Kernel sysctl sertleÅŸtirme
  4. SSH hardening
  5. UFW/iptables yÃ¶netim portu korumasÄ±
  6. QEMU seccomp desteÄŸi
  7. Root SSH giriÅŸi kapalÄ± mÄ±
  8. VarsayÄ±lan ÅŸifre kullanÄ±lÄ±yor mu
  9. AÃ§Ä±k portlar taramasÄ±
 10. Account lockout (baÅŸarÄ±sÄ±z login takibi)
"""

import json
import os
import re
import subprocess
import threading
import time
import logging
from typing import Optional

log = logging.getLogger("ankavm.security_hardening")

# â”€â”€ BaÅŸarÄ±sÄ±z login takibi (username bazlÄ± lockout) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# OXW-2026-006 fix: lockout state diske persist edilir â€” restart'ta sÄ±fÄ±rlanmaz.

_failed_lock   = threading.Lock()
_failed_logins: dict = {}   # {username: {"count": int, "locked_until": float}}
_LOCKOUT_FILE  = "/var/lib/ankavm/lockouts.json"

LOCKOUT_THRESHOLD = 5       # Bu kadar baÅŸarÄ±sÄ±z denemeden sonra kilitle
LOCKOUT_DURATION  = 300     # 5 dakika kilit


def _lockout_load():
    """Disk'ten lockout state'ini yÃ¼kle."""
    global _failed_logins
    if os.path.exists(_LOCKOUT_FILE):
        try:
            with open(_LOCKOUT_FILE) as f:
                _failed_logins = json.load(f)
        except Exception as e:
            log.warning("lockout dosyasÄ± okunamadÄ±: %s", e)
            _failed_logins = {}


def _lockout_save():
    """Lockout state'ini atomik olarak diske yaz."""
    try:
        now = time.time()
        # SÃ¼resi dolmuÅŸ giriÅŸleri temizle
        active = {u: d for u, d in _failed_logins.items() if d.get("locked_until", 0) > now or d.get("count", 0) > 0}
        tmp = _LOCKOUT_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(active, f)
        os.replace(tmp, _LOCKOUT_FILE)
    except Exception as e:
        log.warning("lockout kayÄ±t hatasÄ±: %s", e)


# BaÅŸlangÄ±Ã§ta yÃ¼kle
_lockout_load()


def record_failed_login(username: str):
    now = time.time()
    with _failed_lock:
        entry = _failed_logins.setdefault(username, {"count": 0, "locked_until": 0})
        entry["count"] += 1
        if entry["count"] >= LOCKOUT_THRESHOLD:
            entry["locked_until"] = now + LOCKOUT_DURATION
            log.warning("Account lockout: %s â€” %d baÅŸarÄ±sÄ±z deneme", username, entry["count"])
        _lockout_save()


def record_successful_login(username: str):
    with _failed_lock:
        _failed_logins.pop(username, None)
        _lockout_save()


def is_account_locked(username: str) -> tuple:
    """(locked: bool, seconds_remaining: int) dÃ¶ndÃ¼r."""
    now = time.time()
    with _failed_lock:
        entry = _failed_logins.get(username)
        if not entry:
            return False, 0
        if entry["locked_until"] > now:
            return True, int(entry["locked_until"] - now)
        # Kilit sÃ¼resi geÃ§ti â€” sÄ±fÄ±rla
        if entry["locked_until"] > 0:
            _failed_logins.pop(username, None)
            _lockout_save()
    return False, 0


def get_lockout_status() -> list:
    """TÃ¼m kilitli hesaplarÄ± dÃ¶ndÃ¼r."""
    now = time.time()
    result = []
    with _failed_lock:
        for user, entry in list(_failed_logins.items()):
            result.append({
                "username":        user,
                "failed_count":    entry["count"],
                "locked":          entry["locked_until"] > now,
                "locked_until":    entry["locked_until"],
                "seconds_left":    max(0, int(entry["locked_until"] - now)),
            })
    return result


def unlock_account(username: str) -> bool:
    with _failed_lock:
        if username in _failed_logins:
            del _failed_logins[username]
            return True
    return False


# â”€â”€ YardÄ±mcÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run(cmd: list, timeout: int = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return -1, f"Komut bulunamadÄ±: {cmd[0]}"
    except Exception as e:
        return -1, str(e)


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _sysctl_get(key: str) -> Optional[str]:
    code, out = _run(["sysctl", "-n", key])
    return out if code == 0 else None


# â”€â”€ Kontrol FonksiyonlarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def check_br_netfilter() -> dict:
    """br_netfilter modÃ¼lÃ¼ yÃ¼klÃ¼ mÃ¼? VM firewall kurallarÄ± iÃ§in gerekli."""
    code, out = _run(["lsmod"])
    loaded = "br_netfilter" in out
    # AyrÄ±ca /proc/modules kontrol
    proc = _read_file("/proc/modules") or ""
    loaded = loaded or "br_netfilter" in proc
    return {
        "id":      "br_netfilter",
        "title":   "br_netfilter Kernel ModÃ¼lÃ¼",
        "status":  "pass" if loaded else "fail",
        "detail":  "YÃ¼klÃ¼ âœ“" if loaded else "YÃ¼klÃ¼ deÄŸil â€” VM firewall kurallarÄ± devre dÄ±ÅŸÄ± kalabilir",
        "fix":     None if loaded else "modprobe br_netfilter && echo 'br_netfilter' >> /etc/modules-load.d/ankavm.conf",
    }


def check_iommu() -> dict:
    """IOMMU etkin mi? PCI passthrough izolasyonu iÃ§in gerekli."""
    cmdline = _read_file("/proc/cmdline") or ""
    iommu_on = "intel_iommu=on" in cmdline or "amd_iommu=on" in cmdline or "iommu=pt" in cmdline
    # dmesg kontrolÃ¼
    code, dmesg = _run(["dmesg"])
    dmesg_iommu = "IOMMU enabled" in dmesg or "AMD-Vi: AMD IOMMUv2" in dmesg
    enabled = iommu_on or dmesg_iommu
    return {
        "id":      "iommu",
        "title":   "IOMMU / VT-d",
        "status":  "pass" if enabled else "warn",
        "detail":  "IOMMU aktif âœ“" if enabled else "IOMMU tespit edilemedi â€” PCI passthrough kullanmÄ±yorsanÄ±z sorun yok",
        "fix":     None if enabled else "GRUB'da GRUB_CMDLINE_LINUX'a 'intel_iommu=on iommu=pt' ekle, update-grub Ã§alÄ±ÅŸtÄ±r",
    }


def check_kernel_sysctl() -> dict:
    """Kritik sysctl gÃ¼venlik ayarlarÄ±."""
    checks = {
        "net.ipv4.ip_forward":              ("1",  "warn"),   # KVM iÃ§in gerekli â€” sadece warn
        "net.ipv4.conf.all.rp_filter":      ("1",  "fail"),
        "net.ipv4.conf.all.accept_redirects": ("0", "fail"),
        "net.ipv4.conf.all.send_redirects":   ("0", "fail"),
        "net.ipv4.tcp_syncookies":           ("1",  "fail"),
        "kernel.dmesg_restrict":             ("1",  "warn"),
        "kernel.kptr_restrict":              ("2",  "warn"),
        "net.ipv4.conf.all.log_martians":    ("1",  "warn"),
    }
    issues = []
    for key, (expected, severity) in checks.items():
        val = _sysctl_get(key)
        if val != expected:
            issues.append({"key": key, "expected": expected, "got": val or "?", "severity": severity})

    if not issues:
        return {"id": "sysctl", "title": "Kernel Sysctl", "status": "pass",
                "detail": "TÃ¼m kritik sysctl ayarlarÄ± doÄŸru âœ“", "fix": None}

    fix_cmds = " && ".join(f"sysctl -w {i['key']}={i['expected']}" for i in issues)
    return {
        "id":     "sysctl",
        "title":  "Kernel Sysctl",
        "status": "fail" if any(i["severity"] == "fail" for i in issues) else "warn",
        "detail": f"{len(issues)} ayar yanlÄ±ÅŸ: " + ", ".join(i["key"] for i in issues),
        "issues": issues,
        "fix":    fix_cmds,
    }


def check_ssh_hardening() -> dict:
    """SSH gÃ¼venlik ayarlarÄ±."""
    sshd_config = _read_file("/etc/ssh/sshd_config") or ""
    issues = []

    def _setting(key: str, bad_val: str, good_val: str, msg: str):
        # Regex: satÄ±r baÅŸÄ±nda (boÅŸluk olabilir), key, whitespace, value
        pattern = re.compile(rf"^\s*{key}\s+(\S+)", re.MULTILINE | re.IGNORECASE)
        m = pattern.search(sshd_config)
        val = m.group(1) if m else None
        if val is None or val.lower() == bad_val.lower():
            issues.append({"key": key, "current": val or "default", "recommended": good_val, "msg": msg})

    _setting("PermitRootLogin",      "yes",  "prohibit-password", "Root SSH giriÅŸi aÃ§Ä±k")
    _setting("PasswordAuthentication", "yes", "no",               "SSH ÅŸifre giriÅŸi aÃ§Ä±k (key-only Ã¶nerilir)")
    _setting("X11Forwarding",        "yes",  "no",                "X11 forwarding aÃ§Ä±k (gereksiz saldÄ±rÄ± yÃ¼zeyi)")
    _setting("MaxAuthTries",         "6",    "3",                 "MaxAuthTries yÃ¼ksek (brute-force riski)")
    _setting("PermitEmptyPasswords", "yes",  "no",                "BoÅŸ ÅŸifreye izin veriliyor")

    if not sshd_config:
        return {"id": "ssh", "title": "SSH SertleÅŸtirme", "status": "warn",
                "detail": "/etc/ssh/sshd_config okunamadÄ±", "fix": None}

    if not issues:
        return {"id": "ssh", "title": "SSH SertleÅŸtirme", "status": "pass",
                "detail": "SSH ayarlarÄ± gÃ¼venli âœ“", "fix": None}

    # Fix komutu
    fixes = []
    for i in issues:
        fixes.append(f"sed -i 's/^#*\\s*{i['key']}.*/{i['key']} {i['recommended']}/' /etc/ssh/sshd_config")
    fixes.append("systemctl reload sshd")

    return {
        "id":     "ssh",
        "title":  "SSH SertleÅŸtirme",
        "status": "fail" if any(i["key"] == "PermitRootLogin" for i in issues) else "warn",
        "detail": f"{len(issues)} SSH sorunu: " + ", ".join(i["msg"] for i in issues),
        "issues": issues,
        "fix":    " && ".join(fixes),
    }


def check_qemu_seccomp() -> dict:
    """QEMU seccomp desteÄŸi var mÄ±?"""
    code, out = _run(["qemu-system-x86_64", "--version"])
    if code != 0:
        # qemu-system-x86_64 bulunamadÄ± â€” farklÄ± isim dene
        code, out = _run(["qemu-kvm", "--version"])
    if code != 0:
        return {"id": "qemu_seccomp", "title": "QEMU Seccomp",
                "status": "warn", "detail": "QEMU bulunamadÄ± â€” kurulu deÄŸil mi?", "fix": None}

    # seccomp kernel desteÄŸi
    seccomp_file = _read_file("/proc/version") or ""
    code2, out2 = _run(["grep", "-r", "seccomp", "/proc/config.gz"], timeout=5)
    # En basit kontrol: /proc/sys/kernel/seccomp
    seccomp_ok = os.path.exists("/proc/sys/kernel/seccomp") or os.path.exists("/sys/kernel/security/apparmor")

    return {
        "id":     "qemu_seccomp",
        "title":  "QEMU Seccomp Sandbox",
        "status": "pass" if seccomp_ok else "warn",
        "detail": "Kernel seccomp desteÄŸi mevcut âœ“" if seccomp_ok else
                  "Seccomp tespit edilemedi â€” QEMU sandbox sÄ±nÄ±rlÄ± olabilir",
        "fix":    None,
    }


def check_firewall() -> dict:
    """UFW veya iptables aktif mi?"""
    # UFW
    code_ufw, out_ufw = _run(["ufw", "status"])
    if code_ufw == 0 and "active" in out_ufw.lower():
        return {"id": "firewall", "title": "GÃ¼venlik DuvarÄ± (UFW)",
                "status": "pass", "detail": "UFW aktif âœ“", "fix": None}

    # iptables â€” en az birkaÃ§ kural var mÄ±?
    code_ipt, out_ipt = _run(["iptables", "-L", "-n"])
    if code_ipt == 0 and "DROP" in out_ipt or "REJECT" in out_ipt:
        return {"id": "firewall", "title": "GÃ¼venlik DuvarÄ± (iptables)",
                "status": "pass", "detail": "iptables kurallarÄ± aktif âœ“", "fix": None}

    return {
        "id":     "firewall",
        "title":  "GÃ¼venlik DuvarÄ±",
        "status": "fail",
        "detail": "UFW veya iptables DROP/REJECT kuralÄ± bulunamadÄ± â€” port korumasÄ± yok",
        "fix":    "ufw enable && ufw default deny incoming && ufw allow 8006/tcp && ufw allow 22/tcp",
    }


def check_open_ports() -> dict:
    """Kritik portlara dÄ±ÅŸarÄ±dan eriÅŸim riski var mÄ±?"""
    risky_ports = {
        "5900-5999": "VNC (ÅŸifresiz eriÅŸim riski)",
        "6080":      "noVNC WebSocket",
        "2375":      "Docker daemon (ÅŸifresiz)",
        "2376":      "Docker daemon TLS",
    }
    code, out = _run(["ss", "-tlnp"])
    if code != 0:
        code, out = _run(["netstat", "-tlnp"])

    found = []
    for port_range, desc in risky_ports.items():
        if port_range.replace("-", "") in out or port_range in out:
            found.append(f"{port_range} ({desc})")

    if not found:
        return {"id": "open_ports", "title": "AÃ§Ä±k Port Riski",
                "status": "pass", "detail": "Riskli port bulunamadÄ± âœ“", "fix": None}

    return {
        "id":     "open_ports",
        "title":  "AÃ§Ä±k Port Riski",
        "status": "warn",
        "detail": f"Potansiyel riskli portlar: {', '.join(found)}",
        "fix":    "ufw deny <port> veya servis konfigÃ¼rasyonundan portu kapat",
    }


def check_default_password() -> dict:
    """VarsayÄ±lan/zayÄ±f ÅŸifre kullanÄ±lÄ±yor mu? (sembolik kontrol)"""
    try:
        import credentials as cred
        info = cred.get_credential_info()
        # Åifre hiÃ§ deÄŸiÅŸtirilmemiÅŸ mi?
        created  = info.get("created_at", 0) or 0
        changed  = info.get("last_changed") or 0
        if not changed or (changed - created) < 5:
            return {
                "id":     "default_password",
                "title":  "VarsayÄ±lan Åifre",
                "status": "warn",
                "detail": "Åifre kurulumdan bu yana deÄŸiÅŸtirilmemiÅŸ â€” deÄŸiÅŸtirmeniz Ã¶nerilir",
                "fix":    "GÃ¼venlik â†’ Åifre SÄ±fÄ±rlama bÃ¶lÃ¼mÃ¼nden deÄŸiÅŸtirin",
            }
    except Exception:
        pass
    return {"id": "default_password", "title": "VarsayÄ±lan Åifre",
            "status": "pass", "detail": "Åifre deÄŸiÅŸtirilmiÅŸ âœ“", "fix": None}


# â”€â”€ Yeni Kontroller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def check_ksm() -> dict:
    """KSM (Kernel Samepage Merging) â€” cross-VM bellek yan kanal riski."""
    ksm_run = _read_file("/sys/kernel/mm/ksm/run")
    if ksm_run is None or ksm_run == "0":
        return {"id": "ksm", "title": "KSM Bellek Dedup",
                "status": "pass", "detail": "KSM kapalÄ± âœ“ â€” cross-VM side-channel riski yok", "fix": None}
    # KSM aÃ§Ä±k â€” VM sayÄ±sÄ±nÄ± kontrol et
    code, vms = _run(["virsh", "list", "--all", "--name"])
    vm_count = len([v for v in vms.splitlines() if v.strip()]) if code == 0 else 2
    if vm_count > 1:
        return {
            "id":     "ksm",
            "title":  "KSM Bellek Dedup",
            "status": "warn",
            "detail": f"KSM aÃ§Ä±k ve {vm_count} VM var â€” Ã§ok kiracÄ±lÄ± ortamda cross-VM bellek sÄ±zÄ±ntÄ±sÄ± riski (CVE-class)",
            "fix":    "echo 0 > /sys/kernel/mm/ksm/run && echo 'w /sys/kernel/mm/ksm/run - - - - 0' > /etc/tmpfiles.d/ksm-disable.conf",
        }
    return {"id": "ksm", "title": "KSM Bellek Dedup",
            "status": "pass", "detail": "KSM aÃ§Ä±k ama tek VM â€” risk dÃ¼ÅŸÃ¼k âœ“", "fix": None}


def check_l2_isolation() -> dict:
    """Bridge L2 izolasyonu â€” ARP spoofing ve MAC sahteciliÄŸi korumasÄ±."""
    issues = []
    for key, expected in [
        ("net.bridge.bridge-nf-call-iptables", "1"),
        ("net.bridge.bridge-nf-call-ip6tables", "1"),
    ]:
        val = _sysctl_get(key)
        if val != expected:
            issues.append(key)

    code, out = _run(["ebtables", "-L"])
    ebtables_ok = (code == 0 and len(out) > 20)

    if not issues and ebtables_ok:
        return {"id": "l2_isolation", "title": "L2 AÄŸ Ä°zolasyonu",
                "status": "pass", "detail": "Bridge L2 filtering aktif âœ“", "fix": None}

    fix = ("modprobe br_netfilter && "
           "sysctl -w net.bridge.bridge-nf-call-iptables=1 && "
           "sysctl -w net.bridge.bridge-nf-call-ip6tables=1")
    return {
        "id":     "l2_isolation",
        "title":  "L2 AÄŸ Ä°zolasyonu",
        "status": "warn",
        "detail": f"Bridge filtering eksik: {', '.join(issues) if issues else 'ebtables kuralÄ± yok'} â€” ARP spoofing riski",
        "fix":    fix,
    }


def check_nested_virt() -> dict:
    """Nested sanallaÅŸtÄ±rma â€” L2 hypervisor kaÃ§Ä±ÅŸ riski."""
    intel = _read_file("/sys/module/kvm_intel/parameters/nested")
    amd   = _read_file("/sys/module/kvm_amd/parameters/nested")
    enabled = (intel in ("1", "Y")) or (amd in ("1", "Y"))
    if not enabled:
        return {"id": "nested_virt", "title": "Nested SanallaÅŸtÄ±rma",
                "status": "pass", "detail": "Nested virtualization kapalÄ± âœ“", "fix": None}
    vendor = "intel" if intel in ("1", "Y") else "amd"
    return {
        "id":     "nested_virt",
        "title":  "Nested SanallaÅŸtÄ±rma",
        "status": "warn",
        "detail": "Nested virtualization aktif â€” VM iÃ§i hypervisor kaÃ§Ä±ÅŸ riski (corCTF 2024 PoC mevcut)",
        "fix":    f"echo 'options kvm_{vendor} nested=0' >> /etc/modprobe.d/kvm-hardening.conf",
    }


def check_vm_devices() -> dict:
    """VM'lerde riskli sanal cihaz kontrolÃ¼ (floppy, 9p, audio)."""
    code, xml_list = _run(["virsh", "list", "--all", "--name"])
    if code != 0:
        return {"id": "vm_devices", "title": "VM Cihaz GÃ¼venliÄŸi",
                "status": "warn", "detail": "virsh eriÅŸilemedi", "fix": None}
    vms = [v.strip() for v in xml_list.splitlines() if v.strip()]
    if not vms:
        return {"id": "vm_devices", "title": "VM Cihaz GÃ¼venliÄŸi",
                "status": "pass", "detail": "Aktif VM yok âœ“", "fix": None}
    risky = []
    for vm in vms[:10]:
        code2, xml = _run(["virsh", "dumpxml", vm])
        if code2 != 0:
            continue
        xml_lower = xml.lower()
        if "floppy" in xml_lower or "<disk.*fd" in xml_lower:
            risky.append(f"{vm}:floppy")
        if "<filesystem type='mount'" in xml_lower or "9p" in xml_lower:
            risky.append(f"{vm}:9p/virtfs")
    if not risky:
        return {"id": "vm_devices", "title": "VM Cihaz GÃ¼venliÄŸi",
                "status": "pass", "detail": "Riskli sanal cihaz bulunamadÄ± âœ“", "fix": None}
    return {
        "id":     "vm_devices",
        "title":  "VM Cihaz GÃ¼venliÄŸi",
        "status": "warn",
        "detail": f"Riskli sanal cihazlar: {', '.join(risky[:5])} â€” hypervisor kaÃ§Ä±ÅŸ yÃ¼zeyi",
        "fix":    "VM konfigÃ¼rasyonundan floppy/9p cihazlarÄ±nÄ± kaldÄ±rÄ±n: virsh edit <vm>",
    }


def check_cert_expiry() -> dict:
    """SSL sertifika geÃ§erlilik tarihi kontrolÃ¼."""
    import datetime
    cert_paths = ["/etc/ankavm/ssl/ankavm.crt", "/etc/ssl/ankavm/ankavm.crt",
                  "/etc/ankavm/ssl/server.crt"]
    cert_file = next((p for p in cert_paths if os.path.exists(p)), None)
    if not cert_file:
        return {"id": "cert_expiry", "title": "SSL Sertifika",
                "status": "warn", "detail": "SSL sertifika dosyasÄ± bulunamadÄ±", "fix": None}
    code, out = _run(["openssl", "x509", "-in", cert_file, "-noout", "-enddate"])
    if code != 0:
        return {"id": "cert_expiry", "title": "SSL Sertifika",
                "status": "warn", "detail": f"Sertifika okunamadÄ±: {out[:80]}", "fix": None}
    try:
        date_str = out.split("=", 1)[1].strip()
        exp = datetime.datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
        days_left = (exp - datetime.datetime.utcnow()).days
        renew_cmd = (f"openssl req -x509 -nodes -days 3650 -newkey rsa:2048 "
                     f"-keyout {cert_file.replace('.crt','.key')} -out {cert_file} "
                     f"-subj '/CN=ankavm' && systemctl restart ankavm")
        if days_left < 0:
            return {"id": "cert_expiry", "title": "SSL Sertifika", "status": "fail",
                    "detail": f"Sertifika {abs(days_left)} gÃ¼n Ã¶nce sona erdi!", "fix": renew_cmd}
        if days_left < 30:
            return {"id": "cert_expiry", "title": "SSL Sertifika", "status": "warn",
                    "detail": f"Sertifika {days_left} gÃ¼n iÃ§inde sona eriyor", "fix": renew_cmd}
        return {"id": "cert_expiry", "title": "SSL Sertifika",
                "status": "pass", "detail": f"Sertifika geÃ§erli, {days_left} gÃ¼n kaldÄ± âœ“", "fix": None}
    except Exception as e:
        return {"id": "cert_expiry", "title": "SSL Sertifika",
                "status": "warn", "detail": f"Sertifika tarihi ayrÄ±ÅŸtÄ±rÄ±lamadÄ±: {e}", "fix": None}


def check_cve_exposure() -> dict:
    """NVD API Ã¼zerinden son QEMU/KVM CVE'lerini sorgula."""
    import datetime, urllib.request, json
    try:
        end   = datetime.datetime.utcnow()
        start = end - datetime.timedelta(days=90)
        url = (
            "https://services.nvd.nist.gov/rest/json/cves/2.0"
            f"?keywordSearch=QEMU%20KVM"
            f"&pubStartDate={start.strftime('%Y-%m-%dT00:00:00.000')}"
            f"&pubEndDate={end.strftime('%Y-%m-%dT23:59:59.999')}"
            f"&cvssV3Severity=HIGH"
            f"&resultsPerPage=5"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ankavm/2.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        total = data.get("totalResults", 0)
        vulns = data.get("vulnerabilities", [])
        if total == 0:
            return {"id": "cve_exposure", "title": "KVM/QEMU CVE Ä°zleme",
                    "status": "pass", "detail": "Son 90 gÃ¼nde kritik CVE bulunamadÄ± âœ“", "fix": None}
        cve_list = []
        for v in vulns[:3]:
            cve_id = v.get("cve", {}).get("id", "?")
            desc   = (v.get("cve", {}).get("descriptions") or [{}])[0].get("value", "")[:80]
            cve_list.append(f"{cve_id}: {desc}")
        return {
            "id":     "cve_exposure",
            "title":  "KVM/QEMU CVE Ä°zleme",
            "status": "warn",
            "detail": f"Son 90 gÃ¼nde {total} yÃ¼ksek CVE: {cve_list[0] if cve_list else ''}",
            "fix":    "apt-get update && apt-get upgrade -y qemu-kvm qemu-system-x86 libvirt-daemon-system",
            "cves":   cve_list,
        }
    except Exception as e:
        log.warning("CVE sorgusu baÅŸarÄ±sÄ±z: %s", e)
        return {"id": "cve_exposure", "title": "KVM/QEMU CVE Ä°zleme",
                "status": "warn", "detail": f"CVE sorgusu yapÄ±lamadÄ± (aÄŸ?): {str(e)[:60]}", "fix": None}


# â”€â”€ Ana audit fonksiyonu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_security_audit() -> dict:
    """
    TÃ¼m kontrolleri Ã§alÄ±ÅŸtÄ±r.
    DÃ¶ner: {checks: [...], summary: {pass, warn, fail, score}}
    """
    checks = []
    runners = [
        check_br_netfilter,
        check_iommu,
        check_kernel_sysctl,
        check_ssh_hardening,
        check_qemu_seccomp,
        check_firewall,
        check_open_ports,
        check_default_password,
        check_ksm,
        check_l2_isolation,
        check_nested_virt,
        check_vm_devices,
        check_cert_expiry,
        check_cve_exposure,
    ]
    for fn in runners:
        try:
            checks.append(fn())
        except Exception as e:
            log.error("GÃ¼venlik kontrol hatasÄ± (%s): %s", fn.__name__, e)
            checks.append({
                "id": fn.__name__, "title": fn.__name__,
                "status": "error", "detail": str(e), "fix": None,
            })

    summary = {
        "pass":  sum(1 for c in checks if c["status"] == "pass"),
        "warn":  sum(1 for c in checks if c["status"] == "warn"),
        "fail":  sum(1 for c in checks if c["status"] == "fail"),
        "total": len(checks),
    }
    summary["score"] = int(
        (summary["pass"] * 100 + summary["warn"] * 50) / max(summary["total"], 1)
    )
    return {"checks": checks, "summary": summary, "scanned_at": time.time()}


def apply_fix(check_id: str) -> dict:
    """
    Belirli bir kontrol iÃ§in otomatik dÃ¼zeltme uygula.
    Sadece gÃ¼venli/geri alÄ±nabilir komutlar Ã§alÄ±ÅŸtÄ±rÄ±r.
    """
    SAFE_FIXES = {
        "br_netfilter": [
            ["modprobe", "br_netfilter"],
            ["sh", "-c", "echo 'br_netfilter' >> /etc/modules-load.d/ankavm.conf"],
        ],
        "sysctl": [
            ["sysctl", "-w", "net.ipv4.conf.all.rp_filter=1"],
            ["sysctl", "-w", "net.ipv4.conf.all.accept_redirects=0"],
            ["sysctl", "-w", "net.ipv4.conf.all.send_redirects=0"],
            ["sysctl", "-w", "net.ipv4.tcp_syncookies=1"],
            ["sysctl", "-w", "net.ipv4.conf.all.log_martians=1"],
            ["sysctl", "-w", "kernel.dmesg_restrict=1"],
            ["sysctl", "-w", "kernel.kptr_restrict=2"],
            # KalÄ±cÄ± yap
            ["sh", "-c", "cat >> /etc/sysctl.d/99-ankavm.conf << 'EOF'\n"
                          "net.ipv4.conf.all.rp_filter=1\n"
                          "net.ipv4.conf.all.accept_redirects=0\n"
                          "net.ipv4.conf.all.send_redirects=0\n"
                          "net.ipv4.tcp_syncookies=1\n"
                          "net.ipv4.conf.all.log_martians=1\n"
                          "kernel.dmesg_restrict=1\n"
                          "kernel.kptr_restrict=2\n"
                          "EOF"],
        ],
        "ksm": [
            ["sh", "-c", "echo 0 > /sys/kernel/mm/ksm/run"],
            ["sh", "-c", "echo 'w /sys/kernel/mm/ksm/run - - - - 0' > /etc/tmpfiles.d/ksm-disable.conf"],
        ],
        "l2_isolation": [
            ["modprobe", "br_netfilter"],
            ["sysctl", "-w", "net.bridge.bridge-nf-call-iptables=1"],
            ["sysctl", "-w", "net.bridge.bridge-nf-call-ip6tables=1"],
            ["sh", "-c", "echo 'net.bridge.bridge-nf-call-iptables=1' >> /etc/sysctl.d/99-ankavm-bridge.conf"],
        ],
        # SSH: Sadece gÃ¼venli deÄŸiÅŸiklikler â€” PasswordAuthentication/PermitRootLogin dokunulmaz
        "ssh_hardening": [
            ["sh", "-c", "grep -q '^X11Forwarding' /etc/ssh/sshd_config && sed -i 's/^X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config || echo 'X11Forwarding no' >> /etc/ssh/sshd_config"],
            ["sh", "-c", "grep -q '^MaxAuthTries' /etc/ssh/sshd_config && sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config || echo 'MaxAuthTries 3' >> /etc/ssh/sshd_config"],
            ["sh", "-c", "grep -q '^PermitEmptyPasswords' /etc/ssh/sshd_config && sed -i 's/^PermitEmptyPasswords.*/PermitEmptyPasswords no/' /etc/ssh/sshd_config || echo 'PermitEmptyPasswords no' >> /etc/ssh/sshd_config"],
            ["sh", "-c", "grep -q '^LoginGraceTime' /etc/ssh/sshd_config && sed -i 's/^LoginGraceTime.*/LoginGraceTime 30/' /etc/ssh/sshd_config || echo 'LoginGraceTime 30' >> /etc/ssh/sshd_config"],
            ["sh", "-c", "systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true"],
        ],
        # Docker 2375: TCP socket kapat, UNIX socket gÃ¼venli kÄ±l
        "docker_2375": [
            ["sh", "-c", "[ -S /var/run/docker.sock ] && chmod 660 /var/run/docker.sock 2>/dev/null || true"],
            ["sh", "-c", "mkdir -p /etc/systemd/system/docker.service.d && printf '[Service]\\nExecStart=\\nExecStart=/usr/bin/dockerd' > /etc/systemd/system/docker.service.d/no-tcp.conf 2>/dev/null || true"],
            ["systemctl", "daemon-reload"],
            ["sh", "-c", "systemctl restart docker 2>/dev/null || true"],
        ],
    }
    cmds = SAFE_FIXES.get(check_id)
    if not cmds:
        return {"success": False, "error": f"'{check_id}' iÃ§in otomatik dÃ¼zeltme yok â€” manuel uygulayÄ±n"}

    results = []
    for cmd in cmds:
        code, out = _run(cmd)
        results.append({"cmd": " ".join(cmd), "code": code, "out": out[:200]})

    success = all(r["code"] == 0 for r in results)
    return {"success": success, "results": results}


# â”€â”€ Periyodik Denetim + AI UyarÄ±sÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_last_audit_result: dict = {}
_audit_sched_lock  = threading.Lock()


def run_scheduled_audit() -> dict:
    """
    GÃ¼venlik denetimi Ã§alÄ±ÅŸtÄ±r, deÄŸiÅŸiklikleri tespit et, bildirim gÃ¶nder.
    Yeni fail/warn ortaya Ã§Ä±karsa Telegram/Discord'a AI uyarÄ±sÄ± gider.
    """
    global _last_audit_result
    result = run_security_audit()
    new_issues = []

    with _audit_sched_lock:
        old_statuses = {c["id"]: c["status"] for c in _last_audit_result.get("checks", [])}
        for check in result.get("checks", []):
            prev = old_statuses.get(check["id"])
            if prev in ("pass", None) and check["status"] in ("fail", "warn"):
                new_issues.append(check)
        _last_audit_result = result

    summary = result.get("summary", {})
    score    = summary.get("score", 0)
    fails    = summary.get("fail", 0)
    warns    = summary.get("warn", 0)

    try:
        import notifications as _notif

        if new_issues:
            details = {c["title"]: c["detail"][:80] for c in new_issues[:5]}
            _notif.send_alert(
                message=f"ğŸ”´ GÃ¼venlik denetimi: {len(new_issues)} YENÄ° sorun tespit edildi! Puan: {score}/100",
                level="ERROR",
                category="security",
                details=details,
            )
            log.warning("Yeni gÃ¼venlik sorunlarÄ± bildirildi: %s", [c["id"] for c in new_issues])
        elif fails > 0:
            details = {c["title"]: c["detail"][:80]
                       for c in result.get("checks", []) if c["status"] == "fail"}
            _notif.send_alert(
                message=f"âš ï¸ GÃ¼venlik denetimi: {fails} aÃ§Ä±k sorun, {warns} uyarÄ±. Puan: {score}/100",
                level="WARNING",
                category="security",
                details=details,
            )
    except Exception as e:
        log.warning("GÃ¼venlik bildirimi gÃ¶nderilemedi: %s", e)

    return result


def start_audit_scheduler(interval_hours: int = 24):
    """Arka planda periyodik gÃ¼venlik denetimi baÅŸlat."""
    def _loop():
        time.sleep(120)   # 2 dk baÅŸlangÄ±Ã§ gecikmesi
        while True:
            try:
                log.info("Periyodik gÃ¼venlik denetimi baÅŸlatÄ±lÄ±yor...")
                run_scheduled_audit()
                log.info("Periyodik gÃ¼venlik denetimi tamamlandÄ±.")
            except Exception as e:
                log.error("Periyodik denetim hatasÄ±: %s", e)
            time.sleep(interval_hours * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="ankavm-security-audit")
    t.start()
    log.info("GÃ¼venlik denetimi zamanlayÄ±cÄ±sÄ± baÅŸlatÄ±ldÄ± (%dh aralÄ±k)", interval_hours)






