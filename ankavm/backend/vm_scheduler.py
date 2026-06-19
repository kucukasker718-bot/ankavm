"""
vm_scheduler.py â€” ankavm VM ZamanlanmÄ±ÅŸ GÃ¶rev YÃ¶neticisi
VM'leri belirli gÃ¼n/saat kombinasyonlarÄ±nda otomatik baÅŸlat, durdur,
yeniden baÅŸlat veya snapshot al.
"""

import json
import os
import time
import threading
import subprocess
import logging
import uuid
from datetime import datetime

logger = logging.getLogger("ankavm.vm_scheduler")

# Zamanlama verilerinin saklandÄ±ÄŸÄ± dosya
SCHEDULES_FILE = "/var/lib/ankavm/vm_schedules.json"

# Thread-safe eriÅŸim iÃ§in kilit
_lock = threading.Lock()

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# YardÄ±mcÄ± fonksiyonlar
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ensure_data_dir():
    """Veri dizininin var olduÄŸundan emin ol."""
    os.makedirs(os.path.dirname(SCHEDULES_FILE), exist_ok=True)


def _load_schedules() -> list:
    """JSON dosyasÄ±ndan zamanlama listesini oku."""
    _ensure_data_dir()
    if not os.path.exists(SCHEDULES_FILE):
        return []
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Zamanlama dosyasÄ± okunamadÄ±: %s", exc)
        return []


def _save_schedules(schedules: list) -> None:
    """Zamanlama listesini JSON dosyasÄ±na yaz."""
    _ensure_data_dir()
    try:
        with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.error("Zamanlama dosyasÄ± yazÄ±lamadÄ±: %s", exc)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Genel API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_schedules() -> list:
    """TÃ¼m zamanlama kayÄ±tlarÄ±nÄ± dÃ¶ndÃ¼r."""
    with _lock:
        return _load_schedules()


def add_schedule(
    vm_id: str,
    vm_name: str,
    action: str,
    hour: int,
    minute: int,
    days: list = None,
    enabled: bool = True,
) -> dict:
    """
    Yeni zamanlama ekle.

    action: "start" | "shutdown" | "reboot" | "snapshot"
    days  : HaftanÄ±n gÃ¼nleri listesi (0=Pzt â€¦ 6=Paz). BoÅŸ = her gÃ¼n.
    DÃ¶ndÃ¼rÃ¼r: OluÅŸturulan zamanlama dict'i.
    """
    valid_actions = {"start", "shutdown", "reboot", "snapshot"}
    if action not in valid_actions:
        raise ValueError(f"GeÃ§ersiz aksiyon: {action}. GeÃ§erli: {valid_actions}")
    if not (0 <= hour <= 23):
        raise ValueError("hour 0-23 arasÄ±nda olmalÄ±dÄ±r.")
    if not (0 <= minute <= 59):
        raise ValueError("minute 0-59 arasÄ±nda olmalÄ±dÄ±r.")

    schedule = {
        "id": str(uuid.uuid4()),
        "vm_id": vm_id,
        "vm_name": vm_name,
        "action": action,
        "hour": hour,
        "minute": minute,
        "days": days if days is not None else [],   # BoÅŸ = her gÃ¼n
        "enabled": enabled,
        "created_at": datetime.utcnow().isoformat(),
        "last_run": None,
    }

    with _lock:
        schedules = _load_schedules()
        schedules.append(schedule)
        _save_schedules(schedules)

    logger.info(
        "Zamanlama eklendi: %s â€” vm=%s aksiyon=%s %02d:%02d gÃ¼nler=%s",
        schedule["id"], vm_name, action, hour, minute, days,
    )
    return schedule


def update_schedule(sched_id: str, **kwargs) -> bool:
    """
    Mevcut zamanlamayÄ± gÃ¼ncelle.
    GÃ¼ncellenebilir alanlar: action, hour, minute, days, enabled.
    DÃ¶ndÃ¼rÃ¼r: True (baÅŸarÄ±lÄ±) | False (bulunamadÄ±).
    """
    allowed_keys = {"action", "hour", "minute", "days", "enabled", "vm_name"}

    with _lock:
        schedules = _load_schedules()
        for sched in schedules:
            if sched["id"] == sched_id:
                for key, value in kwargs.items():
                    if key in allowed_keys:
                        sched[key] = value
                _save_schedules(schedules)
                logger.info("Zamanlama gÃ¼ncellendi: %s", sched_id)
                return True

    logger.warning("GÃ¼ncellenecek zamanlama bulunamadÄ±: %s", sched_id)
    return False


def delete_schedule(sched_id: str) -> bool:
    """
    ZamanlamayÄ± sil.
    DÃ¶ndÃ¼rÃ¼r: True (silindi) | False (bulunamadÄ±).
    """
    with _lock:
        schedules = _load_schedules()
        new_schedules = [s for s in schedules if s["id"] != sched_id]
        if len(new_schedules) == len(schedules):
            logger.warning("Silinecek zamanlama bulunamadÄ±: %s", sched_id)
            return False
        _save_schedules(new_schedules)

    logger.info("Zamanlama silindi: %s", sched_id)
    return True


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Aksiyon uygulayÄ±cÄ±
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _execute_action(sched: dict) -> None:
    """ZamanlanmÄ±ÅŸ aksiyonu gerÃ§ekten Ã§alÄ±ÅŸtÄ±r."""
    vm_id = sched["vm_id"]
    vm_name = sched["vm_name"]
    action = sched["action"]

    logger.info(
        "Zamanlama Ã§alÄ±ÅŸÄ±yor: id=%s vm=%s aksiyon=%s",
        sched["id"], vm_name, action,
    )

    try:
        if action == "snapshot":
            # virsh snapshot-create-as ile snapshot oluÅŸtur
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            snap_name = f"scheduled-{vm_name}-{ts}"
            cmd = [
                "virsh", "snapshot-create-as",
                vm_name,
                snap_name,
                "--atomic",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info("Snapshot oluÅŸturuldu: %s", snap_name)
            else:
                logger.error(
                    "Snapshot hatasÄ± (vm=%s): %s", vm_name, result.stderr.strip()
                )
        else:
            # vm_manager'Ä± yerel import et (dÃ¶ngÃ¼sel baÄŸÄ±mlÄ±lÄ±ÄŸÄ± Ã¶nlemek iÃ§in)
            import vm_manager  # noqa: PLC0415

            if action == "start":
                vm_manager.start_vm(vm_id)
                logger.info("VM baÅŸlatÄ±ldÄ±: %s", vm_name)
            elif action == "shutdown":
                vm_manager.stop_vm(vm_id)
                logger.info("VM durduruldu: %s", vm_name)
            elif action == "reboot":
                vm_manager.reboot_vm(vm_id)
                logger.info("VM yeniden baÅŸlatÄ±ldÄ±: %s", vm_name)

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(
            "Aksiyon Ã§alÄ±ÅŸtÄ±rÄ±lÄ±rken hata (vm=%s aksiyon=%s): %s",
            vm_name, action, exc,
        )


def _update_last_run(sched_id: str) -> None:
    """last_run alanÄ±nÄ± ÅŸimdiki zamana gÃ¼ncelle."""
    now_iso = datetime.utcnow().isoformat()
    with _lock:
        schedules = _load_schedules()
        for sched in schedules:
            if sched["id"] == sched_id:
                sched["last_run"] = now_iso
                break
        _save_schedules(schedules)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ZamanlayÄ±cÄ± dÃ¶ngÃ¼sÃ¼
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _scheduler_loop() -> None:
    """
    Daemon thread'de Ã§alÄ±ÅŸan ana dÃ¶ngÃ¼.
    Her dakika tetiklenen zamanlamalarÄ± kontrol eder.
    """
    logger.info("VM zamanlayÄ±cÄ± dÃ¶ngÃ¼sÃ¼ baÅŸladÄ±.")
    while True:
        try:
            _check_schedules()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("ZamanlayÄ±cÄ± dÃ¶ngÃ¼sÃ¼nde beklenmeyen hata: %s", exc)
        time.sleep(60)


def _check_schedules() -> None:
    """Åu anki saat/gÃ¼n ile eÅŸleÅŸen zamanlamalarÄ± Ã§alÄ±ÅŸtÄ±r."""
    now = datetime.utcnow()  # Sunucu UTC saatiyle Ã§alÄ±ÅŸÄ±r; gerekirse localtime al
    current_hour = now.hour
    current_minute = now.minute
    current_weekday = now.weekday()  # 0=Pzt, 6=Paz
    now_ts = now.timestamp()

    with _lock:
        schedules = _load_schedules()

    for sched in schedules:
        if not sched.get("enabled", False):
            continue

        # Saat/dakika kontrolÃ¼
        if sched["hour"] != current_hour or sched["minute"] != current_minute:
            continue

        # GÃ¼n kontrolÃ¼ â€” boÅŸ liste = her gÃ¼n
        days = sched.get("days", [])
        if days and current_weekday not in days:
            continue

        # Son Ã§alÄ±ÅŸma kontrolÃ¼ â€” 55 saniyeden kÄ±sa Ã¶nce Ã§alÄ±ÅŸtÄ±ysa atla
        last_run = sched.get("last_run")
        if last_run:
            try:
                last_run_dt = datetime.fromisoformat(last_run)
                elapsed = now_ts - last_run_dt.timestamp()
                if elapsed < 55:
                    logger.debug(
                        "Zamanlama %s son %d sn Ã¶nce Ã§alÄ±ÅŸtÄ±, atlanÄ±yor.",
                        sched["id"], int(elapsed),
                    )
                    continue
            except (ValueError, OSError):
                pass  # AyrÄ±ÅŸtÄ±rma hatasÄ± â†’ yine de Ã§alÄ±ÅŸtÄ±r

        # Aksiyonu ayrÄ± thread'de Ã§alÄ±ÅŸtÄ±r (dÃ¶ngÃ¼yÃ¼ bloklamaz)
        threading.Thread(
            target=_run_and_update,
            args=(sched,),
            daemon=True,
            name=f"sched-{sched['id'][:8]}",
        ).start()


def _run_and_update(sched: dict) -> None:
    """Aksiyonu Ã§alÄ±ÅŸtÄ±r ve last_run'Ä± gÃ¼ncelle."""
    _execute_action(sched)
    _update_last_run(sched["id"])


def start_scheduler() -> threading.Thread:
    """
    VM zamanlayÄ±cÄ±sÄ±nÄ± daemon thread olarak baÅŸlat.
    DÃ¶ndÃ¼rÃ¼r: BaÅŸlatÄ±lan Thread nesnesi.
    """
    t = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="vm-scheduler",
    )
    t.start()
    logger.info("VM zamanlayÄ±cÄ± thread'i baÅŸlatÄ±ldÄ±.")
    return t






