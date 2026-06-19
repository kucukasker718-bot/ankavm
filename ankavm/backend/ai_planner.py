"""
ankavm AI Planner
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
AI tabanlÄ± kaynak planlama ve doÄŸal dil komut iÅŸleme.
YapÄ±landÄ±rma: /var/lib/ankavm/ai_recommendations.json
"""

import json
import logging
import os
import threading
import time
import subprocess
from datetime import datetime

log = logging.getLogger("ankavm.ai_planner")

RECS_FILE = "/var/lib/ankavm/ai_recommendations.json"
NL_HISTORY = "/var/log/ankavm/nl_commands.jsonl"
_lock = threading.Lock()

try:
    import ai_agent
    AI_AVAILABLE = True
    log.info("ai_agent modÃ¼lÃ¼ yÃ¼klendi.")
except Exception:
    AI_AVAILABLE = False
    log.warning("ai_agent modÃ¼lÃ¼ bulunamadÄ±. Mock kural motoru kullanÄ±lacak.")

try:
    import system_monitor as _sysmon
    SYSMON_AVAILABLE = True
except Exception:
    _sysmon = None
    SYSMON_AVAILABLE = False

try:
    import perf_history as _perf
    PERF_AVAILABLE = True
except Exception:
    _perf = None
    PERF_AVAILABLE = False


# â”€â”€ YardÄ±mcÄ± fonksiyonlar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ensure_dir(path: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass


def _virsh(args: list) -> str:
    try:
        r = subprocess.run(
            ["virsh"] + args,
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip()
    except Exception as e:
        log.debug("virsh hatasÄ±: %s", e)
        return ""


def _get_system_context() -> str:
    """Mevcut VM'leri, CPU/RAM kullanÄ±mÄ±nÄ± ve disk durumunu topla. Kompakt JSON dÃ¶ndÃ¼r."""
    ctx = {}

    # VM listesi
    try:
        raw = _virsh(["list", "--all"])
        vms = []
        for line in raw.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 3:
                vms.append({"id": parts[0], "name": parts[1], "state": parts[2]})
        ctx["vms"] = vms
    except Exception as e:
        ctx["vms"] = []
        log.debug("VM listesi alÄ±namadÄ±: %s", e)

    # Sistem metrikleri
    if SYSMON_AVAILABLE:
        try:
            ctx["system"] = _sysmon.get_system_metrics()
        except Exception as e:
            log.debug("system_monitor hatasÄ±: %s", e)
            ctx["system"] = {}
    else:
        try:
            import psutil
            ctx["system"] = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "mem_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
            }
        except Exception:
            ctx["system"] = {}

    return json.dumps(ctx, ensure_ascii=False)


def _ai_query(prompt: str) -> str:
    """AI provider'a sorgu gÃ¶nder, ham metin yanÄ±t dÃ¶ndÃ¼r."""
    if AI_AVAILABLE:
        try:
            return ai_agent.query(prompt)
        except Exception as e:
            log.warning("AI sorgu hatasÄ±: %s", e)
    return None


def _parse_json_response(text: str) -> any:
    """AI yanÄ±tÄ±ndan JSON bloÄŸu ayÄ±kla."""
    if not text:
        return None
    try:
        # Kod bloÄŸu varsa Ã§Ä±kar
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        return json.loads(text.strip())
    except Exception:
        return None


# â”€â”€ Ana fonksiyonlar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def analyze_resources() -> dict:
    """Sistem durumunu AI ile analiz et ve Ã¶neriler Ã¼ret."""
    try:
        ctx = _get_system_context()
        ts = datetime.now().isoformat()

        if AI_AVAILABLE:
            prompt = (
                "Analyze this hypervisor state and give optimization recommendations in JSON. "
                "Return a JSON array of objects with keys: type (warning|suggestion|critical), "
                "title, description, action. Context:\n" + ctx
            )
            raw = _ai_query(prompt)
            recs = _parse_json_response(raw) or []
            if not isinstance(recs, list):
                recs = []
        else:
            # Mock kural motoru
            recs = []
            try:
                data = json.loads(ctx)
                sys_data = data.get("system", {})
                cpu = sys_data.get("cpu_percent", 0)
                mem = sys_data.get("mem_percent", 0)
                if cpu > 80:
                    recs.append({
                        "type": "warning",
                        "title": "YÃ¼ksek CPU KullanÄ±mÄ±",
                        "description": f"CPU kullanÄ±mÄ± %{cpu:.1f} seviyesinde.",
                        "action": "YoÄŸun VM'leri farklÄ± saatlere daÄŸÄ±tÄ±n veya kaynak sÄ±nÄ±rlarÄ±nÄ± ayarlayÄ±n.",
                    })
                if mem > 85:
                    recs.append({
                        "type": "warning",
                        "title": "YÃ¼ksek Bellek KullanÄ±mÄ±",
                        "description": f"RAM kullanÄ±mÄ± %{mem:.1f} seviyesinde.",
                        "action": "Gereksiz VM'leri durdurun veya bellek balon sÃ¼rÃ¼cÃ¼sÃ¼ kullanÄ±n.",
                    })
            except Exception as e:
                log.debug("Mock analiz hatasÄ±: %s", e)

        result = {"recommendations": recs, "analyzed_at": ts}

        _ensure_dir(RECS_FILE)
        with _lock:
            try:
                with open(RECS_FILE, "w") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log.warning("RECS_FILE yazma hatasÄ±: %s", e)

        return result
    except Exception as e:
        log.error("analyze_resources hatasÄ±: %s", e)
        return {"recommendations": [], "analyzed_at": datetime.now().isoformat(), "error": str(e)}


def get_recommendations() -> dict:
    """KaydedilmiÅŸ AI Ã¶nerilerini oku."""
    try:
        if not os.path.exists(RECS_FILE):
            return {"recommendations": [], "analyzed_at": None}
        with _lock:
            with open(RECS_FILE) as f:
                return json.load(f)
    except Exception as e:
        log.error("get_recommendations hatasÄ±: %s", e)
        return {"recommendations": [], "error": str(e)}


def suggest_vm_sizing(vm_id: str) -> dict:
    """VM'in mevcut kullanÄ±mÄ±na gÃ¶re optimal boyut Ã¶nerisi."""
    try:
        # Mevcut VM bilgisi
        dominfo = _virsh(["dominfo", vm_id])
        current = {}
        for line in dominfo.splitlines():
            if "CPU(s)" in line:
                try:
                    current["vcpus"] = int(line.split(":")[1].strip())
                except Exception:
                    pass
            if "Max memory" in line:
                try:
                    current["memory_kb"] = int(line.split(":")[1].strip().split()[0])
                except Exception:
                    pass

        if AI_AVAILABLE:
            ctx = _get_system_context()
            prompt = (
                f"Based on this VM's usage and hypervisor state, suggest optimal CPU and RAM. "
                f"VM ID: {vm_id}. Current: {json.dumps(current)}. Context: {ctx}. "
                "Return JSON with keys: suggested_vcpus (int), suggested_memory_mb (int), reason (str)."
            )
            raw = _ai_query(prompt)
            suggestion = _parse_json_response(raw) or {}
        else:
            suggestion = {
                "suggested_vcpus": current.get("vcpus", 2),
                "suggested_memory_mb": (current.get("memory_kb", 2097152) // 1024),
                "reason": "AI mevcut deÄŸil. Mevcut deÄŸerler korundu.",
            }

        return {
            "vm_id": vm_id,
            "current": current,
            "suggested_vcpus": suggestion.get("suggested_vcpus"),
            "suggested_memory_mb": suggestion.get("suggested_memory_mb"),
            "reason": suggestion.get("reason", ""),
        }
    except Exception as e:
        log.error("suggest_vm_sizing hatasÄ±: %s", e)
        return {"vm_id": vm_id, "error": str(e)}


def predict_capacity(days: int = 30) -> dict:
    """Son metrik trendine gÃ¶re kapasite tahmini yap."""
    try:
        trend_data = {}
        if PERF_AVAILABLE:
            try:
                trend_data = _perf.get_trend(days=7)
            except Exception as e:
                log.debug("perf_history trend hatasÄ±: %s", e)

        if AI_AVAILABLE and trend_data:
            prompt = (
                f"Analyze this 7-day trend and predict capacity for the next {days} days. "
                f"Trend data: {json.dumps(trend_data)}. "
                "Return JSON with keys: predicted_cpu_pct (float), predicted_mem_pct (float), "
                "days_until_full (int or null), recommendation (str)."
            )
            raw = _ai_query(prompt)
            prediction = _parse_json_response(raw) or {}
        else:
            # Basit lineer tahmin
            try:
                cpu_vals = trend_data.get("cpu", [])
                mem_vals = trend_data.get("mem", [])
                pred_cpu = cpu_vals[-1] if cpu_vals else 50.0
                pred_mem = mem_vals[-1] if mem_vals else 50.0
                days_until = None
                if cpu_vals and len(cpu_vals) >= 2:
                    delta = (cpu_vals[-1] - cpu_vals[0]) / len(cpu_vals)
                    if delta > 0:
                        days_until = int((100 - cpu_vals[-1]) / delta)
            except Exception:
                pred_cpu, pred_mem, days_until = 50.0, 50.0, None

            prediction = {
                "predicted_cpu_pct": pred_cpu,
                "predicted_mem_pct": pred_mem,
                "days_until_full": days_until,
                "recommendation": "AI mevcut deÄŸil. Basit tahmin kullanÄ±ldÄ±.",
            }

        return {
            "days": days,
            "predicted_cpu_pct": prediction.get("predicted_cpu_pct"),
            "predicted_mem_pct": prediction.get("predicted_mem_pct"),
            "days_until_full": prediction.get("days_until_full"),
            "recommendation": prediction.get("recommendation", ""),
        }
    except Exception as e:
        log.error("predict_capacity hatasÄ±: %s", e)
        return {"days": days, "error": str(e)}


def process_natural_language(command: str, username: str = "admin") -> dict:
    """DoÄŸal dil komutunu iÅŸle ve Ã§alÄ±ÅŸtÄ±r."""
    try:
        ts = datetime.now().isoformat()

        if AI_AVAILABLE:
            prompt = (
                "Convert this hypervisor natural language command to a structured JSON action. "
                "Return JSON with keys: action (create_vm|start_vm|stop_vm|list_vms|delete_vm|"
                "get_info|snapshot|unknown), params (dict), confirmation_required (bool), "
                f"human_response (str). Command: '{command}'"
            )
            raw = _ai_query(prompt)
            parsed = _parse_json_response(raw) or {}
        else:
            # Basit anahtar kelime eÅŸleme
            cmd_lower = command.lower()
            if any(w in cmd_lower for w in ["baÅŸlat", "start", "aÃ§"]):
                parsed = {
                    "action": "start_vm",
                    "params": {},
                    "confirmation_required": True,
                    "human_response": "VM baÅŸlatma komutu algÄ±landÄ±. LÃ¼tfen onaylayÄ±n.",
                }
            elif any(w in cmd_lower for w in ["durdur", "stop", "kapat"]):
                parsed = {
                    "action": "stop_vm",
                    "params": {},
                    "confirmation_required": True,
                    "human_response": "VM durdurma komutu algÄ±landÄ±. LÃ¼tfen onaylayÄ±n.",
                }
            elif any(w in cmd_lower for w in ["listele", "list", "gÃ¶ster"]):
                parsed = {
                    "action": "list_vms",
                    "params": {},
                    "confirmation_required": False,
                    "human_response": "VM listesi alÄ±nÄ±yor.",
                }
            else:
                parsed = {
                    "action": "unknown",
                    "params": {},
                    "confirmation_required": True,
                    "human_response": "Komut anlaÅŸÄ±lamadÄ±. LÃ¼tfen daha aÃ§Ä±k bir ifade kullanÄ±n.",
                }

        result = {}
        if not parsed.get("confirmation_required", True):
            result = execute_nl_action(parsed.get("action", "unknown"), parsed.get("params", {}))

        # GeÃ§miÅŸe kaydet
        history_entry = {
            "ts": ts,
            "username": username,
            "command": command,
            "parsed": parsed,
            "result": result,
        }
        _ensure_dir(NL_HISTORY)
        try:
            with _lock:
                with open(NL_HISTORY, "a") as f:
                    f.write(json.dumps(history_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning("NL_HISTORY yazma hatasÄ±: %s", e)

        return {**parsed, "execution_result": result}
    except Exception as e:
        log.error("process_natural_language hatasÄ±: %s", e)
        return {"action": "unknown", "error": str(e)}


def execute_nl_action(action: str, params: dict) -> dict:
    """AyrÄ±ÅŸtÄ±rÄ±lmÄ±ÅŸ NL action'Ä± Ã§alÄ±ÅŸtÄ±r."""
    try:
        if action == "list_vms":
            raw = _virsh(["list", "--all"])
            return {"success": True, "result": raw, "message": "VM listesi alÄ±ndÄ±."}

        elif action == "start_vm":
            vm_name = params.get("name") or params.get("vm_name", "")
            if not vm_name:
                return {"success": False, "result": None, "message": "VM adÄ± belirtilmedi."}
            raw = _virsh(["start", vm_name])
            return {"success": True, "result": raw, "message": f"{vm_name} baÅŸlatÄ±ldÄ±."}

        elif action == "stop_vm":
            vm_name = params.get("name") or params.get("vm_name", "")
            if not vm_name:
                return {"success": False, "result": None, "message": "VM adÄ± belirtilmedi."}
            raw = _virsh(["shutdown", vm_name])
            return {"success": True, "result": raw, "message": f"{vm_name} durduruldu."}

        elif action == "get_info":
            vm_name = params.get("name") or params.get("vm_name", "")
            raw = _virsh(["dominfo", vm_name])
            return {"success": True, "result": raw, "message": "VM bilgisi alÄ±ndÄ±."}

        elif action == "snapshot":
            vm_name = params.get("name") or params.get("vm_name", "")
            snap_name = params.get("snapshot_name", f"snap-{int(time.time())}")
            raw = _virsh(["snapshot-create-as", vm_name, snap_name])
            return {"success": True, "result": raw, "message": f"Snapshot '{snap_name}' oluÅŸturuldu."}

        else:
            return {"success": False, "result": None, "message": f"Desteklenmeyen action: {action}"}

    except Exception as e:
        log.error("execute_nl_action hatasÄ±: %s", e)
        return {"success": False, "result": None, "message": str(e)}


def start_periodic_analysis(interval_hours: int = 24):
    """Periyodik analizi daemon thread olarak baÅŸlat."""
    def _worker():
        while True:
            try:
                log.info("Periyodik AI analizi baÅŸlÄ±yor...")
                analyze_resources()
                log.info("Periyodik AI analizi tamamlandÄ±.")
            except Exception as e:
                log.error("Periyodik analiz hatasÄ±: %s", e)
            time.sleep(interval_hours * 3600)

    t = threading.Thread(target=_worker, daemon=True, name="ai-planner-periodic")
    t.start()
    log.info("Periyodik AI analizi %d saatte bir Ã§alÄ±ÅŸacak.", interval_hours)
    return t






