"""
resource_quota.py â€” VM baÅŸÄ±na kaynak limitleri (ankavm Hypervisor)
"""

import subprocess
import json
import logging
import os
import threading

log = logging.getLogger("ankavm.quota")

QUOTAS_FILE = "/var/lib/ankavm/quotas.json"
GLOBAL_QUOTA_KEY = "__global__"

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Ä°Ã§ yardÄ±mcÄ±lar
# ---------------------------------------------------------------------------

def _run(*cmd):
    """subprocess.run Ã§alÄ±ÅŸtÄ±rÄ±r; hata fÄ±rlatmaz."""
    try:
        result = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            log.warning("Komut baÅŸarÄ±sÄ±z [%d]: %s | stderr: %s",
                        result.returncode, " ".join(cmd), result.stderr.strip())
        return result
    except FileNotFoundError:
        log.error("Komut bulunamadÄ±: %s", cmd[0])
        return None
    except Exception as exc:
        log.exception("_run hatasÄ±: %s", exc)
        return None


def _load():
    """QUOTAS_FILE'dan kota verilerini yÃ¼kler."""
    try:
        os.makedirs(os.path.dirname(QUOTAS_FILE), exist_ok=True)
        if not os.path.exists(QUOTAS_FILE):
            return {}
        with open(QUOTAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("QUOTAS_FILE okunamadÄ±: %s", exc)
        return {}


def _save(data):
    """Kota verilerini QUOTAS_FILE'a kaydeder."""
    try:
        os.makedirs(os.path.dirname(QUOTAS_FILE), exist_ok=True)
        with open(QUOTAS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        log.error("QUOTAS_FILE yazÄ±lamadÄ±: %s", exc)
        raise

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_quota(vm_id):
    """
    VM'in kota bilgisini dÃ¶ner.
    {"max_vcpus": int, "max_memory_mb": int, "cpu_shares": int, "io_weight": int}
    veya {} (kota tanÄ±mlÄ± deÄŸilse)
    """
    try:
        data = _load()
        return data.get(str(vm_id), {})
    except Exception as exc:
        log.exception("get_quota hatasÄ±: %s", exc)
        return {}


def set_quota(vm_id, vm_name=None, max_vcpus=None, max_memory_mb=None,
              cpu_shares=1024, io_weight=100):
    """
    VM iÃ§in kota ayarlar ve virsh ile uygular.
    """
    with _lock:
        try:
            data = _load()
            vm_id_str = str(vm_id)

            existing = data.get(vm_id_str, {})
            quota = {
                "vm_id": vm_id_str,
                "vm_name": vm_name or existing.get("vm_name", ""),
                "max_vcpus": max_vcpus if max_vcpus is not None else existing.get("max_vcpus"),
                "max_memory_mb": max_memory_mb if max_memory_mb is not None else existing.get("max_memory_mb"),
                "cpu_shares": cpu_shares,
                "io_weight": io_weight,
            }

            # virsh setvcpus
            if quota["max_vcpus"] is not None:
                r = _run("virsh", "setvcpus", str(vm_id),
                         str(quota["max_vcpus"]), "--maximum", "--config")
                if r and r.returncode == 0:
                    log.info("vCPU limiti ayarlandÄ±: vm=%s vcpus=%d", vm_id, quota["max_vcpus"])

            # virsh setmaxmem
            if quota["max_memory_mb"] is not None:
                r = _run("virsh", "setmaxmem", str(vm_id),
                         f"{quota['max_memory_mb']}M", "--config")
                if r and r.returncode == 0:
                    log.info("Maksimum bellek ayarlandÄ±: vm=%s mem=%dM", vm_id, quota["max_memory_mb"])

            # cgroups cpu.shares (opsiyonel)
            try:
                cgroup_path = f"/sys/fs/cgroup/cpu/machine.slice/machine-qemu\\x2d{vm_id_str}.scope/cpu.shares"
                if os.path.exists(cgroup_path):
                    with open(cgroup_path, "w", encoding="utf-8") as f:
                        f.write(str(cpu_shares))
                    log.info("cgroup cpu.shares ayarlandÄ±: vm=%s shares=%d", vm_id, cpu_shares)
            except (OSError, PermissionError) as exc:
                log.warning("cgroup cpu.shares ayarlanamadÄ±: %s", exc)

            # io_weight (blkio)
            try:
                blkio_path = f"/sys/fs/cgroup/blkio/machine.slice/machine-qemu\\x2d{vm_id_str}.scope/blkio.weight"
                if os.path.exists(blkio_path):
                    with open(blkio_path, "w", encoding="utf-8") as f:
                        f.write(str(io_weight))
            except (OSError, PermissionError) as exc:
                log.warning("blkio weight ayarlanamadÄ±: %s", exc)

            data[vm_id_str] = quota
            _save(data)

            log.info("Kota kaydedildi: vm=%s", vm_id)
            return {"success": True, "quota": quota}
        except Exception as exc:
            log.exception("set_quota hatasÄ±: %s", exc)
            return {"success": False, "error": str(exc)}


def delete_quota(vm_id):
    """VM kotasÄ±nÄ± siler."""
    with _lock:
        try:
            data = _load()
            vm_id_str = str(vm_id)
            if vm_id_str not in data:
                return {"success": False, "error": "Kota bulunamadÄ±"}
            data.pop(vm_id_str)
            _save(data)
            log.info("Kota silindi: vm=%s", vm_id)
            return {"success": True}
        except Exception as exc:
            log.exception("delete_quota hatasÄ±: %s", exc)
            return {"success": False, "error": str(exc)}


def list_quotas():
    """TÃ¼m VM kotalarÄ±nÄ± listeler (global kota hariÃ§)."""
    try:
        data = _load()
        return [v for k, v in data.items() if k != GLOBAL_QUOTA_KEY]
    except Exception as exc:
        log.exception("list_quotas hatasÄ±: %s", exc)
        return []


def get_global_quota():
    """
    Global kota ayarlarÄ±nÄ± dÃ¶ner.
    {"max_vms_per_user": int, "max_total_vcpus": int, "max_total_memory_gb": int}
    """
    try:
        data = _load()
        return data.get(GLOBAL_QUOTA_KEY, {
            "max_vms_per_user": 10,
            "max_vcpus_per_user": 32,
            "max_total_vcpus": 64,
            "max_memory_mb_per_user": 131072,
            "max_total_memory_gb": 256,
        })
    except Exception as exc:
        log.exception("get_global_quota hatasÄ±: %s", exc)
        return {}


def set_global_quota(max_vms_per_user=None, max_total_vcpus=None, max_total_memory_gb=None):
    """Global kota ayarlarÄ±nÄ± gÃ¼nceller."""
    with _lock:
        try:
            data = _load()
            current = data.get(GLOBAL_QUOTA_KEY, {})

            if max_vms_per_user is not None:
                current["max_vms_per_user"] = max_vms_per_user
            if max_total_vcpus is not None:
                current["max_total_vcpus"] = max_total_vcpus
            if max_total_memory_gb is not None:
                current["max_total_memory_gb"] = max_total_memory_gb

            data[GLOBAL_QUOTA_KEY] = current
            _save(data)

            log.info("Global kota gÃ¼ncellendi: %s", current)
            return {"success": True, "global_quota": current}
        except Exception as exc:
            log.exception("set_global_quota hatasÄ±: %s", exc)
            return {"success": False, "error": str(exc)}


def check_quota(username, vcpus, memory_mb):
    """
    rapor #25 fix: KullanÄ±cÄ± baÅŸÄ±na VM/vCPU/RAM kota kontrolÃ¼.
    DÃ¶nÃ¼ÅŸ: (ok: bool, reason: str)
    """
    try:
        global_quota = get_global_quota()
        all_quotas = list_quotas()

        max_vcpus = global_quota.get("max_total_vcpus", 64)
        max_memory_gb = global_quota.get("max_total_memory_gb", 256)
        max_vms = global_quota.get("max_vms_per_user", 10)

        # rapor #25: KullanÄ±cÄ±ya atanmÄ±ÅŸ VM'ler Ã¼zerinden kota hesapla
        try:
            import user_manager as _um
            user_vm_ids = set(_um.get_user_vms(username))
        except Exception:
            user_vm_ids = set()

        user_quotas = [q for q in all_quotas if q.get("vm_id") in user_vm_ids]
        user_vcpus   = sum(q.get("max_vcpus") or 0 for q in user_quotas)
        user_mem_mb  = sum(q.get("max_memory_mb") or 0 for q in user_quotas)
        user_vm_count = len(user_quotas)

        # Sistem geneli kontrol
        total_vcpus    = sum(q.get("max_vcpus") or 0 for q in all_quotas)
        total_memory_gb = sum(q.get("max_memory_mb") or 0 for q in all_quotas) / 1024

        if total_vcpus + vcpus > max_vcpus:
            return False, (f"Toplam vCPU limiti aÅŸÄ±lÄ±yor: "
                           f"mevcut={total_vcpus}, istenen={vcpus}, limit={max_vcpus}")

        if total_memory_gb + (memory_mb / 1024) > max_memory_gb:
            return False, (f"Toplam bellek limiti aÅŸÄ±lÄ±yor: "
                           f"mevcut={total_memory_gb:.1f}GB, "
                           f"istenen={memory_mb/1024:.1f}GB, limit={max_memory_gb}GB")

        # rapor #25: KullanÄ±cÄ± baÅŸÄ±na VM sayÄ±sÄ± kontrolÃ¼
        if user_vm_count >= max_vms:
            return False, (f"KullanÄ±cÄ± '{username}' VM limitine ulaÅŸtÄ±: "
                           f"mevcut={user_vm_count}, limit={max_vms}")

        # rapor #25: KullanÄ±cÄ± baÅŸÄ±na vCPU kontrolÃ¼
        user_max_vcpus = global_quota.get("max_vcpus_per_user", max_vcpus)
        if user_vcpus + vcpus > user_max_vcpus:
            return False, (f"KullanÄ±cÄ± '{username}' vCPU limitini aÅŸÄ±yor: "
                           f"mevcut={user_vcpus}, istenen={vcpus}, limit={user_max_vcpus}")

        # rapor #25: KullanÄ±cÄ± baÅŸÄ±na RAM kontrolÃ¼ (MB)
        user_max_mem_mb = global_quota.get("max_memory_mb_per_user", max_memory_gb * 1024)
        if user_mem_mb + memory_mb > user_max_mem_mb:
            return False, (f"KullanÄ±cÄ± '{username}' bellek limitini aÅŸÄ±yor: "
                           f"mevcut={user_mem_mb}MB, istenen={memory_mb}MB, limit={user_max_mem_mb}MB")

        return True, "OK"
    except Exception as exc:
        log.exception("check_quota hatasÄ±: %s", exc)
        return False, f"Kota kontrolÃ¼ baÅŸarÄ±sÄ±z: {exc}"


def apply_quota_to_vm(vm_id):
    """Mevcut kotayÄ± virsh ile VM'e uygular."""
    try:
        quota = get_quota(vm_id)
        if not quota:
            return {"success": False, "error": "Kota bulunamadÄ±"}

        return set_quota(
            vm_id=vm_id,
            vm_name=quota.get("vm_name"),
            max_vcpus=quota.get("max_vcpus"),
            max_memory_mb=quota.get("max_memory_mb"),
            cpu_shares=quota.get("cpu_shares", 1024),
            io_weight=quota.get("io_weight", 100),
        )
    except Exception as exc:
        log.exception("apply_quota_to_vm hatasÄ±: %s", exc)
        return {"success": False, "error": str(exc)}






