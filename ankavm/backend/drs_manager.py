"""
ankavm DRS — Distributed Resource Scheduler (basic single-host + multi-host advisor)
─────────────────────────────────────────────────────────────────────────────────
VM placement advisor + cross-node rebalance (DPM ile beraber).

Tek host: VM auto-balance içinde CPU pinning / NUMA önerisi.
Multi host: cluster_manager mevcutsa → migrate önerisi.

API:
    analyze() -> dict     (VM dağılım analizi)
    suggest_moves() -> list  (taşıma önerileri)
    auto_balance(dry_run=True) -> dict  (önerileri uygula)
    get_policy() / set_policy(...)
"""

import json, time, subprocess, logging, threading
from pathlib import Path

log = logging.getLogger("drs_manager")
_CFG = Path("/var/lib/ankavm/drs_config.json")
_LOCK = threading.Lock()

_DEFAULT_POLICY = {
    "enabled":            False,
    "aggressiveness":     "moderate",   # conservative | moderate | aggressive
    "cpu_threshold_high": 80,           # % - migrate trigger
    "cpu_threshold_low":  20,
    "mem_threshold_high": 85,
    "mem_threshold_low":  30,
    "min_imbalance_pct":  20,           # < %20 imbalance varsa hareket etme
    "check_interval_sec": 300,
    "respect_affinity":   True,
}


def get_policy() -> dict:
    if _CFG.exists():
        try:
            return {**_DEFAULT_POLICY, **json.loads(_CFG.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT_POLICY)


def set_policy(**kwargs) -> dict:
    with _LOCK:
        cfg = get_policy()
        for k, v in kwargs.items():
            if k in _DEFAULT_POLICY:
                cfg[k] = v
        _CFG.parent.mkdir(parents=True, exist_ok=True)
        _CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return cfg


def _get_vm_metrics() -> list:
    """Çalışan VM'lerin CPU/RAM yüzdesi."""
    out = []
    try:
        r = subprocess.run(["virsh", "list", "--state-running", "--name"],
                           capture_output=True, text=True, timeout=10)
        for vm in r.stdout.splitlines():
            vm = vm.strip()
            if not vm:
                continue
            # virsh domstats — cpu time, balloon (memory)
            r2 = subprocess.run(["virsh", "domstats", vm, "--vcpu", "--balloon"],
                                capture_output=True, text=True, timeout=8)
            entry = {"vm": vm, "cpu_time_ns": 0, "vcpus": 1,
                     "mem_used_kb": 0, "mem_total_kb": 0}
            for line in r2.stdout.splitlines():
                line = line.strip()
                if "vcpu.current=" in line:
                    entry["vcpus"] = int(line.split("=")[1])
                elif "balloon.current=" in line:
                    entry["mem_used_kb"] = int(line.split("=")[1])
                elif "balloon.maximum=" in line:
                    entry["mem_total_kb"] = int(line.split("=")[1])
            out.append(entry)
    except Exception as e:
        log.warning("DRS metrics fetch hatası: %s", e)
    return out


def analyze() -> dict:
    """Mevcut yük dağılımını ve imbalance'ı analiz et."""
    vms = _get_vm_metrics()
    if not vms:
        return {"vms": [], "imbalance_pct": 0, "needs_action": False}

    total_mem = sum(v["mem_used_kb"] for v in vms)
    avg_mem   = total_mem / len(vms) if vms else 0
    if avg_mem > 0:
        deviations = [abs(v["mem_used_kb"] - avg_mem) / avg_mem * 100 for v in vms]
        imbalance = sum(deviations) / len(deviations)
    else:
        imbalance = 0

    cfg = get_policy()
    return {
        "vms":           vms,
        "total_vms":     len(vms),
        "avg_mem_kb":    int(avg_mem),
        "imbalance_pct": round(imbalance, 1),
        "needs_action":  imbalance > cfg["min_imbalance_pct"],
        "policy":        cfg,
    }


def suggest_moves() -> list:
    """
    Multi-node ortamı için: yüksek yüklü host'tan düşük yüklü host'a VM taşıma önerileri.
    Tek-node: önerilen vCPU/RAM ayar değişiklikleri.
    """
    analysis = analyze()
    if not analysis.get("needs_action"):
        return []

    cfg = get_policy()
    cpu_high = cfg["cpu_threshold_high"]
    suggestions = []

    # Tek host modunda — RAM kullanımına göre öneri
    vms = analysis["vms"]
    avg = analysis["avg_mem_kb"]
    for v in vms:
        if avg == 0:
            continue
        deviation = (v["mem_used_kb"] - avg) / avg * 100
        if deviation > 50:
            suggestions.append({
                "vm":         v["vm"],
                "action":     "consider_migrate_or_resize",
                "reason":     f"RAM kullanımı ortalamadan %{int(deviation)} yüksek",
                "current_mb": v["mem_used_kb"] // 1024,
                "avg_mb":     int(avg / 1024),
            })

    return suggestions


def auto_balance(dry_run: bool = True) -> dict:
    """Önerileri uygula (tek-host — şu an sadece dry_run mantığında)."""
    suggestions = suggest_moves()
    if dry_run or not suggestions:
        return {
            "dry_run":     dry_run,
            "suggestions": suggestions,
            "applied":     0,
        }
    # Gerçek uygulama: cluster_manager olmadığı için sadece log
    log.info("DRS auto_balance: %d öneri uygulanmadı (cluster_manager yok)", len(suggestions))
    return {
        "dry_run":     False,
        "suggestions": suggestions,
        "applied":     0,
        "note":        "Multi-node cluster_manager olmadan auto-migrate devre dışı",
    }






