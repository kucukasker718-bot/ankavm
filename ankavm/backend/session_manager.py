"""
session_manager.py â€” ankavm JWT Oturum YÃ¶neticisi
Aktif oturumlarÄ± bellek iÃ§inde takip eder; iptal (revocation) ve
otomatik temizleme desteÄŸi saÄŸlar.
"""

import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ankavm.session_manager")

# JWT sÃ¼resi 12 saat; 13 saatte kesin sona erme kabul edilir
JWT_EXPIRY_HOURS = 12
CLEANUP_THRESHOLD_HOURS = 13

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Bellek iÃ§i depolama
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# { jti (str) â†’ session dict }
_sessions: dict = {}

# RLock: aynÄ± thread iÃ§inde iÃ§ iÃ§e kilitlenmeye izin verir
_lock = threading.RLock()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# YardÄ±mcÄ± fonksiyonlar
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _now_iso() -> str:
    """Åimdiki UTC zamanÄ±nÄ± ISO-8601 formatÄ±nda dÃ¶ndÃ¼r."""
    return datetime.now(timezone.utc).isoformat()


def _age_minutes(created_at_iso: str) -> float:
    """OluÅŸturulma zamanÄ±ndan bu yana geÃ§en sÃ¼reyi dakika olarak hesapla."""
    try:
        created = datetime.fromisoformat(created_at_iso)
        # Timezone-naive ise UTC kabul et
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        return delta.total_seconds() / 60
    except (ValueError, OSError):
        return 0.0


def _format_session(jti: str, session: dict) -> dict:
    """
    Dahili oturum dict'ini API'ye sunulacak biÃ§ime dÃ¶nÃ¼ÅŸtÃ¼r.
    jti'nin tamamÄ±nÄ± aÃ§Ä±klamaz; sadece ilk 8 karakteri session_id olarak kullanÄ±r.
    """
    return {
        "session_id": jti[:8],
        "username": session["username"],
        "ip": session["ip"],
        "user_agent": session["user_agent"],
        "created_at": session["created_at"],
        "last_seen": session["last_seen"],
        "revoked": session["revoked"],
        "age_minutes": round(_age_minutes(session["created_at"]), 1),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Temel API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def register_session(
    jti: str,
    username: str,
    ip: str,
    user_agent: str,
) -> None:
    """
    Yeni JWT oturumunu kaydet.

    jti      : JWT "jti" talebi (benzersiz token kimliÄŸi)
    username : Oturum sahibi kullanÄ±cÄ± adÄ±
    ip       : Ä°stemci IP adresi
    user_agent: HTTP User-Agent baÅŸlÄ±ÄŸÄ±
    """
    now = _now_iso()
    session = {
        "username": username,
        "ip": ip,
        "user_agent": user_agent,
        "created_at": now,
        "last_seen": now,
        "revoked": False,
    }
    with _lock:
        _sessions[jti] = session
    logger.info(
        "Oturum kaydedildi: jti=%s... kullanÄ±cÄ±=%s ip=%s",
        jti[:8], username, ip,
    )


def touch_session(jti: str) -> None:
    """last_seen alanÄ±nÄ± ÅŸimdiki zamana gÃ¼ncelle (her istekte Ã§aÄŸrÄ±lÄ±r)."""
    with _lock:
        if jti in _sessions:
            _sessions[jti]["last_seen"] = _now_iso()


def revoke_session(jti: str) -> bool:
    """
    Oturumu iptal et (revoke).
    DÃ¶ndÃ¼rÃ¼r: True (iptal edildi) | False (oturum bulunamadÄ±).
    """
    with _lock:
        if jti not in _sessions:
            logger.warning("Ä°ptal edilecek oturum bulunamadÄ±: jti=%s...", jti[:8])
            return False
        _sessions[jti]["revoked"] = True

    logger.info(
        "Oturum iptal edildi: jti=%s... kullanÄ±cÄ±=%s",
        jti[:8], _sessions[jti]["username"],
    )
    return True


def revoke_by_short_id(short_id: str) -> bool:
    """session_id (jti'nin ilk 8 karakteri) ile oturumu iptal et."""
    with _lock:
        for jti, sess in _sessions.items():
            if jti[:8] == short_id:
                sess["revoked"] = True
                logger.info("Oturum kÄ±sa ID ile iptal edildi: %s", short_id)
                return True
    return False


def is_revoked(jti: str) -> bool:
    """
    Token'Ä±n iptal edilip edilmediÄŸini kontrol et.
    Bilinmeyen jti â†’ False (JWT kÃ¼tÃ¼phanesi imza/sÃ¼re doÄŸrulamasÄ± yapar).
    """
    with _lock:
        session = _sessions.get(jti)
        if session is None:
            return False
        return session.get("revoked", False)


def revoke_all_user_sessions(username: str) -> int:
    """rapor #16 fix: KullanÄ±cÄ± silindiÄŸinde tÃ¼m aktif JWT tokenlarÄ±nÄ± iptal et.
    Stateless JWT revocation â€” session store Ã¼zerinden tÃ¼m jti'leri iÅŸaretle.
    DÃ¶ndÃ¼rÃ¼r: Ä°ptal edilen oturum sayÄ±sÄ±.
    """
    count = 0
    with _lock:
        for jti, sess in _sessions.items():
            if sess.get("username") == username and not sess.get("revoked", False):
                sess["revoked"] = True
                count += 1
    if count:
        logger.info("KullanÄ±cÄ± silindi â€” %d oturum iptal edildi: %s", count, username)
    return count


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Listeleme API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_active_sessions(username: str = None) -> list:
    """
    Aktif (iptal edilmemiÅŸ, sÃ¼resi dolmamÄ±ÅŸ) oturumlarÄ± dÃ¶ndÃ¼r.

    username : Belirtilirse yalnÄ±zca o kullanÄ±cÄ±ya ait oturumlar dÃ¶ner.
    DÃ¶ndÃ¼rÃ¼r: GÃ¼venli formattaki session dict listesi (jti aÃ§Ä±klanmaz).
    """
    result = []
    with _lock:
        for jti, session in _sessions.items():
            if session["revoked"]:
                continue
            if _age_minutes(session["created_at"]) > JWT_EXPIRY_HOURS * 60:
                continue
            if username and session["username"] != username:
                continue
            result.append(_format_session(jti, session))
    return result


def get_all_sessions() -> list:
    """
    TÃ¼m oturumlarÄ± dÃ¶ndÃ¼r (iptal edilmiÅŸ ve sÃ¼resi dolmuÅŸlar dahil).
    YalnÄ±zca yÃ¶netici kullanÄ±mÄ± iÃ§indir.
    """
    with _lock:
        return [_format_session(jti, sess) for jti, sess in _sessions.items()]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Temizleme
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def cleanup_expired() -> int:
    """
    13 saatten eski oturumlarÄ± bellekten sil.
    DÃ¶ndÃ¼rÃ¼r: Silinen oturum sayÄ±sÄ±.
    """
    threshold_minutes = CLEANUP_THRESHOLD_HOURS * 60
    to_delete = []

    with _lock:
        for jti, session in _sessions.items():
            if _age_minutes(session["created_at"]) > threshold_minutes:
                to_delete.append(jti)
        for jti in to_delete:
            del _sessions[jti]

    if to_delete:
        logger.info("SÃ¼resi dolmuÅŸ %d oturum temizlendi.", len(to_delete))
    else:
        logger.debug("Temizlenecek sÃ¼resi dolmuÅŸ oturum yok.")

    return len(to_delete)


def _cleanup_loop() -> None:
    """Daemon thread dÃ¶ngÃ¼sÃ¼ â€” her 30 dakikada bir temizleme yapar."""
    logger.info("Oturum temizleme thread'i baÅŸladÄ±.")
    import time  # noqa: PLC0415
    while True:
        time.sleep(30 * 60)  # 30 dakika bekle
        try:
            cleanup_expired()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Oturum temizleme sÄ±rasÄ±nda hata: %s", exc)


def start_cleanup_thread() -> threading.Thread:
    """
    Oturum temizleme daemon thread'ini baÅŸlat.
    DÃ¶ndÃ¼rÃ¼r: BaÅŸlatÄ±lan Thread nesnesi.
    """
    t = threading.Thread(
        target=_cleanup_loop,
        daemon=True,
        name="session-cleanup",
    )
    t.start()
    logger.info("Oturum temizleme thread'i baÅŸlatÄ±ldÄ± (30 dk aralÄ±k).")
    return t






