"""
ankavm SIEM Exporter — CEF/LEEF/Syslog formatlarında log akışı
──────────────────────────────────────────────────────────────
Splunk, Elastic, Wazuh, QRadar gibi SIEM sistemlerine event akışı.

Desteklenen formatlar:
  - CEF (Common Event Format — ArcSight)
  - LEEF (QRadar)
  - JSON (Elastic, Splunk HEC)
  - RFC5424 syslog

Çıkış kanalları:
  - syslog (UDP/TCP)
  - HTTP webhook
  - File (rotated)

API:
    configure(format, target) -> dict
    emit(event_type, severity, fields)
    get_config() / set_config(...)
"""

import os, json, time, socket, threading, logging
from pathlib import Path
import urllib.request

log = logging.getLogger("siem_exporter")
_CFG  = Path("/var/lib/ankavm/siem_config.json")
_LOCK = threading.Lock()

_DEFAULT = {
    "enabled":      False,
    "format":       "cef",                # cef | leef | json | syslog
    "transport":    "syslog_udp",         # syslog_udp | syslog_tcp | http | file
    "target_host":  "127.0.0.1",
    "target_port":  514,
    "http_url":     "",
    "http_token":   "",
    "file_path":    "/var/log/ankavm/siem.log",
    "vendor":       "ankavm",
    "product":      "Hypervisor",
    "version":      "2.5.3",
}

_SEVERITY_CEF = {"debug": 1, "info": 3, "notice": 4, "warn": 5,
                 "error": 7, "critical": 9, "alert": 10}


def get_config() -> dict:
    if _CFG.exists():
        try:
            return {**_DEFAULT, **json.loads(_CFG.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT)


def set_config(**kwargs) -> dict:
    with _LOCK:
        cfg = get_config()
        for k, v in kwargs.items():
            if k in _DEFAULT:
                cfg[k] = v
        _CFG.parent.mkdir(parents=True, exist_ok=True)
        _CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return cfg


def _format_cef(event_type: str, severity: str, fields: dict, cfg: dict) -> str:
    """CEF 0|Vendor|Product|Version|EventID|EventName|Severity|key=val key=val"""
    sev = _SEVERITY_CEF.get(severity, 3)
    ext_parts = []
    for k, v in (fields or {}).items():
        v_str = str(v).replace("\\", "\\\\").replace("=", "\\=").replace("|", "\\|").replace("\n", " ")
        ext_parts.append(f"{k}={v_str}")
    return (
        f"CEF:0|{cfg['vendor']}|{cfg['product']}|{cfg['version']}|"
        f"{event_type}|{event_type.replace('_',' ').title()}|{sev}|"
        f"{' '.join(ext_parts)}"
    )


def _format_leef(event_type: str, severity: str, fields: dict, cfg: dict) -> str:
    """LEEF:2.0|Vendor|Product|Version|EventID|^|key=val^key=val"""
    sev = _SEVERITY_CEF.get(severity, 3)
    parts = [f"sev={sev}", f"cat={event_type}"]
    for k, v in (fields or {}).items():
        parts.append(f"{k}={str(v).replace(chr(94), '_')}")  # ^ ayraç
    return (
        f"LEEF:2.0|{cfg['vendor']}|{cfg['product']}|{cfg['version']}|"
        f"{event_type}|^|{'^'.join(parts)}"
    )


def _format_json(event_type: str, severity: str, fields: dict, cfg: dict) -> str:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vendor":    cfg["vendor"],
        "product":   cfg["product"],
        "version":   cfg["version"],
        "event":     event_type,
        "severity":  severity,
        "fields":    fields or {},
    }
    return json.dumps(payload)


def _format_syslog(event_type: str, severity: str, fields: dict, cfg: dict) -> str:
    """RFC5424 syslog."""
    sev_map = {"debug": 7, "info": 6, "notice": 5, "warn": 4,
               "error": 3, "critical": 2, "alert": 1}
    sev = sev_map.get(severity, 6)
    pri = 16 * 8 + sev   # facility 16 = local0
    ts  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    host = socket.gethostname()
    sd = " ".join(f'{k}="{v}"' for k, v in (fields or {}).items())
    return f"<{pri}>1 {ts} {host} ankavm - {event_type} [{sd}]"


def _send_syslog_udp(line: str, cfg: dict):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(line.encode(), (cfg["target_host"], cfg["target_port"]))
    finally:
        sock.close()


def _send_syslog_tcp(line: str, cfg: dict):
    with socket.create_connection((cfg["target_host"], cfg["target_port"]), timeout=5) as s:
        s.sendall((line + "\n").encode())


def _send_http(line: str, cfg: dict):
    req = urllib.request.Request(cfg["http_url"], data=line.encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if cfg.get("http_token"):
        req.add_header("Authorization", f"Splunk {cfg['http_token']}")
    with urllib.request.urlopen(req, timeout=8):
        pass


def _send_file(line: str, cfg: dict):
    p = Path(cfg["file_path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(line + "\n")


def emit(event_type: str, severity: str = "info", fields: dict = None) -> None:
    """Asla bloklamaz — arka planda gönder."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return

    def _send():
        try:
            fmt = cfg["format"]
            if fmt == "cef":
                line = _format_cef(event_type, severity, fields, cfg)
            elif fmt == "leef":
                line = _format_leef(event_type, severity, fields, cfg)
            elif fmt == "json":
                line = _format_json(event_type, severity, fields, cfg)
            else:
                line = _format_syslog(event_type, severity, fields, cfg)

            t = cfg["transport"]
            if t == "syslog_udp":
                _send_syslog_udp(line, cfg)
            elif t == "syslog_tcp":
                _send_syslog_tcp(line, cfg)
            elif t == "http":
                _send_http(line, cfg)
            elif t == "file":
                _send_file(line, cfg)
        except Exception as e:
            log.warning("SIEM emit hatası (%s): %s", event_type, e)

    threading.Thread(target=_send, daemon=True, name=f"siem-{event_type}").start()


def test_connection() -> dict:
    """Yapılandırma test eventi."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "SIEM disabled"}
    try:
        emit("test_event", "info", {"src": "ankavm-test", "msg": "SIEM connection test"})
        return {"ok": True, "message": f"Test event {cfg['transport']} → {cfg['target_host']}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}






