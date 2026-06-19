"""
ankavm SSH Watchdog
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
sshd servisini izler; Ã¶lÃ¼rse otomatik yeniden baÅŸlatÄ±r.
Her 60 saniyede kontrol eder, event log'a yazar.
"""

import logging
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("ankavm.ssh_watchdog")

_state = {
    "active":        False,
    "port_open":     False,
    "last_check":    None,
    "last_restart":  None,
    "restart_count": 0,
    "error":         None,
}
_lock    = threading.Lock()
_thread  = None
_running = False

CHECK_INTERVAL = 60   # saniye
SSH_PORT       = 22
SSH_HOST       = "127.0.0.1"
SSH_SERVICE    = "sshd"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_service_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", SSH_SERVICE],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _is_port_open() -> bool:
    try:
        with socket.create_connection((SSH_HOST, SSH_PORT), timeout=3):
            return True
    except OSError:
        return False


def _restart_sshd() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "restart", SSH_SERVICE],
            capture_output=True, text=True, timeout=30
        )
        return r.returncode == 0
    except Exception as e:
        log.error("sshd restart hatasÄ±: %s", e)
        return False


def _loop():
    global _running
    log.info("SSH watchdog baÅŸlatÄ±ldÄ± (interval=%ds, port=%d)", CHECK_INTERVAL, SSH_PORT)

    while _running:
        active   = _is_service_active()
        port_ok  = _is_port_open()
        now      = _now()
        error    = None

        if not active:
            log.warning("sshd aktif deÄŸil â€” yeniden baÅŸlatÄ±lÄ±yor...")
            ok = _restart_sshd()
            if ok:
                active = _is_service_active()
                port_ok = _is_port_open()
                log.info("sshd yeniden baÅŸlatÄ±ldÄ±. active=%s port=%s", active, port_ok)
                with _lock:
                    _state["restart_count"] += 1
                    _state["last_restart"]   = now
                try:
                    from ankavm.backend import event_logger as _ev
                    _ev.warning("SSH watchdog: sshd Ã¶lmÃ¼ÅŸtÃ¼, yeniden baÅŸlatÄ±ldÄ±.", category="system")
                except Exception:
                    pass
            else:
                error = "sshd restart baÅŸarÄ±sÄ±z"
                log.error("sshd restart baÅŸarÄ±sÄ±z!")
        elif not port_ok:
            error = f"sshd aktif ama port {SSH_PORT} yanÄ±t vermiyor"
            log.warning(error)

        with _lock:
            _state["active"]    = active
            _state["port_open"] = port_ok
            _state["last_check"] = now
            _state["error"]     = error

        for _ in range(CHECK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    log.info("SSH watchdog durduruldu.")


def get_status() -> dict:
    with _lock:
        return dict(_state)


def start():
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread  = threading.Thread(target=_loop, name="ssh-watchdog", daemon=True)
    _thread.start()


def stop():
    global _running
    _running = False






