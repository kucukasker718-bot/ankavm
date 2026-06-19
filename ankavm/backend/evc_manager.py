"""
ankavm EVC â€” Enhanced vMotion Compatibility
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CPU model maskeleme: Eski CPU Ã¶zelliklerini saklayarak yeni nesil host'tan
eski nesil host'a live migrate'i mÃ¼mkÃ¼n kÄ±lar.

VMware EVC mantÄ±ÄŸÄ±: cluster'da en eski CPU'ya gÃ¶re tÃ¼m VM'ler kÄ±sÄ±tlanÄ±r.

API:
    list_baselines() -> list           (Intel/AMD nesil seviyeleri)
    get_current_baseline() -> dict
    set_cluster_baseline(name) -> dict
    get_vm_cpu_features(vm_id) -> dict
    apply_baseline_to_vm(vm_id, baseline) -> dict
"""

import os, json, subprocess, logging
from pathlib import Path

log = logging.getLogger("evc_manager")
_CFG = Path("/var/lib/ankavm/evc.json")


_BASELINES = {
    # Intel
    "intel-merom":     {"vendor": "Intel", "level": 1, "features": ["lm", "sse2", "sse3", "ssse3"]},
    "intel-penryn":    {"vendor": "Intel", "level": 2, "features": ["lm", "sse4.1"]},
    "intel-nehalem":   {"vendor": "Intel", "level": 3, "features": ["lm", "sse4.2", "popcnt"]},
    "intel-westmere":  {"vendor": "Intel", "level": 4, "features": ["lm", "aes", "pclmulqdq"]},
    "intel-sandybridge": {"vendor": "Intel", "level": 5, "features": ["lm", "avx", "xsave"]},
    "intel-ivybridge": {"vendor": "Intel", "level": 6, "features": ["lm", "f16c", "rdrand"]},
    "intel-haswell":   {"vendor": "Intel", "level": 7, "features": ["lm", "avx2", "bmi1", "bmi2", "fma"]},
    "intel-broadwell": {"vendor": "Intel", "level": 8, "features": ["lm", "adx", "rdseed", "smap"]},
    "intel-skylake":   {"vendor": "Intel", "level": 9, "features": ["lm", "avx512f", "xsavec"]},
    "intel-cascadelake": {"vendor": "Intel", "level": 10, "features": ["lm", "avx512_vnni"]},
    "intel-icelake":   {"vendor": "Intel", "level": 11, "features": ["lm", "avx512_vbmi", "vaes"]},
    "intel-sapphirerapids": {"vendor": "Intel", "level": 12, "features": ["lm", "amx-tile", "amx-bf16"]},

    # AMD
    "amd-opteron-g3":  {"vendor": "AMD",   "level": 1, "features": ["lm", "sse4a"]},
    "amd-opteron-g4":  {"vendor": "AMD",   "level": 2, "features": ["lm", "avx", "xop"]},
    "amd-opteron-g5":  {"vendor": "AMD",   "level": 3, "features": ["lm", "fma4", "tbm"]},
    "amd-epyc":        {"vendor": "AMD",   "level": 4, "features": ["lm", "avx2", "rdrand", "rdseed"]},
    "amd-epyc-rome":   {"vendor": "AMD",   "level": 5, "features": ["lm", "clwb"]},
    "amd-epyc-milan":  {"vendor": "AMD",   "level": 6, "features": ["lm", "vaes", "vpclmulqdq"]},
    "amd-epyc-genoa":  {"vendor": "AMD",   "level": 7, "features": ["lm", "avx512f"]},
}


def list_baselines() -> list:
    return [{"name": k, **v} for k, v in _BASELINES.items()]


def get_current_baseline() -> dict:
    if _CFG.exists():
        try:
            return json.loads(_CFG.read_text())
        except Exception:
            pass
    return {"baseline": None, "set_at": None}


def set_cluster_baseline(name: str) -> dict:
    if name not in _BASELINES:
        raise ValueError(f"Bilinmeyen baseline: {name}")
    import time
    cfg = {"baseline": name, "set_at": int(time.time()), **_BASELINES[name]}
    _CFG.parent.mkdir(parents=True, exist_ok=True)
    _CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return cfg


def _read_cpu_flags() -> list:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("flags"):
                    return line.split(":", 1)[1].split()
    except Exception:
        pass
    return []


def detect_host_capability() -> dict:
    """Host'un destekleyebileceÄŸi max baseline."""
    flags = set(_read_cpu_flags())
    best = None
    for name, info in _BASELINES.items():
        if all(f in flags or f == "lm" for f in info["features"]):
            if not best or _BASELINES[best]["level"] < info["level"]:
                best = name
    return {"host_max": best, "host_flags_count": len(flags)}


def get_vm_cpu_features(vm_id: str) -> dict:
    try:
        r = subprocess.run(["virsh", "dumpxml", vm_id],
                           capture_output=True, text=True, timeout=10)
        import re
        cpu_block = re.search(r"<cpu[^>]*>(.*?)</cpu>", r.stdout, re.DOTALL)
        if not cpu_block:
            return {"model": "default", "features": []}
        block = cpu_block.group(1)
        model_match = re.search(r"<model[^>]*>([^<]+)</model>", block)
        features = re.findall(r"<feature[^>]+name='([^']+)'", block)
        return {
            "model":    model_match.group(1) if model_match else "default",
            "features": features,
        }
    except Exception as e:
        return {"error": str(e)}


def apply_baseline_to_vm(vm_id: str, baseline: str = None) -> dict:
    """
    VM'in CPU model'ini baseline'a gÃ¶re deÄŸiÅŸtir.
    NOT: VM kapalÄ± olmalÄ±. virsh edit ile XML modify.
    """
    baseline = baseline or get_current_baseline().get("baseline")
    if not baseline or baseline not in _BASELINES:
        raise ValueError(f"GeÃ§ersiz baseline: {baseline}")

    # VM state check
    state = subprocess.run(["virsh", "domstate", vm_id],
                           capture_output=True, text=True, timeout=5)
    if "shut off" not in state.stdout:
        return {"ok": False, "error": "VM Ã§alÄ±ÅŸÄ±yor â€” Ã¶nce durdur"}

    # CPU model belirleme (libvirt qemu64/Westmere/etc)
    cpu_model_map = {
        "intel-merom":      "Merom",
        "intel-penryn":     "Penryn",
        "intel-nehalem":    "Nehalem",
        "intel-westmere":   "Westmere",
        "intel-sandybridge":"SandyBridge",
        "intel-ivybridge":  "IvyBridge",
        "intel-haswell":    "Haswell",
        "intel-broadwell":  "Broadwell",
        "intel-skylake":    "Skylake-Client",
        "intel-cascadelake":"Cascadelake-Server",
        "intel-icelake":    "Icelake-Server",
        "intel-sapphirerapids":"SapphireRapids",
        "amd-opteron-g3":   "Opteron_G3",
        "amd-opteron-g4":   "Opteron_G4",
        "amd-opteron-g5":   "Opteron_G5",
        "amd-epyc":         "EPYC",
        "amd-epyc-rome":    "EPYC-Rome",
        "amd-epyc-milan":   "EPYC-Milan",
        "amd-epyc-genoa":   "EPYC-Genoa",
    }
    libvirt_model = cpu_model_map.get(baseline, "qemu64")

    # XML modify
    xml = subprocess.run(["virsh", "dumpxml", vm_id],
                         capture_output=True, text=True, timeout=10).stdout
    import re
    new_cpu = (
        f"<cpu mode='custom' match='exact' check='partial'>\n"
        f"  <model fallback='allow'>{libvirt_model}</model>\n"
        f"</cpu>"
    )
    if "<cpu" in xml:
        xml = re.sub(r"<cpu[^>]*>.*?</cpu>", new_cpu, xml, count=1, flags=re.DOTALL)
    else:
        xml = xml.replace("</vcpu>", f"</vcpu>\n  {new_cpu}", 1)

    tmp = Path(f"/tmp/ankavm-evc-{vm_id}.xml")
    tmp.write_text(xml)
    try:
        r = subprocess.run(["virsh", "define", str(tmp)],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return {"ok": True, "vm_id": vm_id, "baseline": baseline,
                    "cpu_model": libvirt_model}
        return {"ok": False, "error": r.stderr.strip()}
    finally:
        try: tmp.unlink()
        except Exception: pass






