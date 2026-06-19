"""ankavm Security Score â€” per-VM and host security assessment"""
import subprocess, logging
from datetime import datetime, timedelta

log = logging.getLogger("security_score")

GRADES = [(90,"A"),(75,"B"),(60,"C"),(40,"D"),(0,"F")]

def _grade(score):
    for threshold, grade in GRADES:
        if score >= threshold: return grade
    return "F"

def score_vm(vm_id, vm_info: dict):
    score = 100
    issues = []
    recs   = []

    ssh_port = int(vm_info.get("ssh_port", 22))
    if ssh_port == 22:
        score -= 10; issues.append("SSH varsayÄ±lan port 22 kullanÄ±yor")
        recs.append("SSH portunu 2222-65535 arasÄ±na taÅŸÄ±yÄ±n")

    if vm_info.get("root_login"):
        score -= 20; issues.append("SSH root giriÅŸi etkin")
        recs.append("PermitRootLogin no yapÄ±n, sudo kullanÄ±n")

    if vm_info.get("password_auth", True):
        score -= 5; issues.append("SSH ÅŸifre kimlik doÄŸrulamasÄ± etkin")
        recs.append("Anahtar tabanlÄ± auth kullanÄ±n, PasswordAuthentication no yapÄ±n")

    cve_count = min(int(vm_info.get("cve_count", 0)), 6)
    if cve_count:
        deduct = cve_count * 5
        score -= deduct; issues.append(f"{cve_count} bilinen CVE tespit edildi")
        recs.append("Sistemi gÃ¼ncelleyin: apt upgrade")

    if not vm_info.get("has_recent_snapshot"):
        score -= 5; issues.append("Son 30 gÃ¼nde snapshot yok")
        recs.append("DÃ¼zenli snapshot alÄ±n")

    if not vm_info.get("has_firewall_rules"):
        score -= 10; issues.append("GÃ¼venlik duvarÄ± kuralÄ± yok")
        recs.append("VM iÃ§in firewall kurallarÄ± ekleyin")
    else:
        score += 10

    score = max(0, min(100, score))
    return {"vm_id": vm_id, "score": score, "grade": _grade(score),
            "issues": issues, "recommendations": recs,
            "checked_at": datetime.now().isoformat()}

def score_all_vms(vms: list):
    results = []
    for vm in (vms or []):
        vm_id = vm.get("id", ""); vm_name = vm.get("name", vm_id)
        info = {"ssh_port": 22, "root_login": False, "password_auth": True,
                "cve_count": 0, "has_recent_snapshot": False, "has_firewall_rules": False}
        try:
            result = score_vm(vm_id, info)
            result["vm_name"] = vm_name
            results.append(result)
        except Exception as e:
            log.error("score_vm %s: %s", vm_id, e)
    return sorted(results, key=lambda x: x["score"])

def get_host_score():
    score = 100; issues = []; recs = []
    try:
        r = subprocess.run(["which","fail2ban-client"],capture_output=True)
        if r.returncode != 0:
            score -= 15; issues.append("fail2ban kurulu deÄŸil")
            recs.append("apt install fail2ban")
    except Exception: pass
    try:
        r = subprocess.run(["ufw","status"],capture_output=True,text=True,timeout=5)
        if "inactive" in r.stdout.lower():
            score -= 20; issues.append("UFW gÃ¼venlik duvarÄ± devre dÄ±ÅŸÄ±")
            recs.append("ufw enable")
    except Exception: pass
    try:
        r = subprocess.run(["apt","list","--upgradable"],capture_output=True,text=True,
                           timeout=30,check=False)
        upgradable = len([l for l in r.stdout.splitlines() if "/" in l])
        if upgradable > 20:
            score -= 15; issues.append(f"{upgradable} gÃ¼ncelleme bekliyor")
            recs.append("apt upgrade")
        elif upgradable > 0:
            score -= 5; issues.append(f"{upgradable} gÃ¼ncelleme bekliyor")
    except Exception: pass
    score = max(0, min(100, score))
    return {"score": score, "grade": _grade(score), "issues": issues,
            "recommendations": recs, "checked_at": datetime.now().isoformat()}






