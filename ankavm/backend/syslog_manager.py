"""
ankavm Syslog Manager — Centralized log viewer.
Reads from journald, /var/log/syslog, /var/log/kern.log.
Supports filtering by level, service, time range.
"""
import subprocess, re, logging
from datetime import datetime, timezone

log = logging.getLogger("ankavm.syslog")

LEVEL_MAP = {
    "emerg": 0, "alert": 1, "crit": 2, "err": 3,
    "warning": 4, "notice": 5, "info": 6, "debug": 7,
}


def _parse_priority(line):
    line_lower = line.lower()
    for keyword, level in [("emerg", "emerg"), ("alert", "alert"), ("crit", "critical"),
                             ("error", "err"), ("err", "err"), ("warn", "warning"),
                             ("notice", "notice"), ("debug", "debug")]:
        if keyword in line_lower:
            return level
    return "info"


def get_journal_logs(lines=200, service=None, level="info", since=None, until=None):
    """Fetch logs from systemd journal."""
    cmd = ["journalctl", "-n", str(lines), "--no-pager", "-o", "short-iso"]
    if service:
        cmd += ["-u", service]
    level_num = LEVEL_MAP.get(level, 6)
    cmd += ["-p", str(level_num)]
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        entries = []
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            entries.append({
                "raw": line,
                "level": _parse_priority(line),
                "source": "journal",
            })
        return {"ok": True, "entries": entries, "count": len(entries)}
    except FileNotFoundError:
        return {"ok": False, "error": "journalctl not available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_syslog(lines=200, level_filter=None, grep=None):
    """Read from /var/log/syslog with optional filtering."""
    for log_file in ["/var/log/syslog", "/var/log/messages", "/var/log/kern.log"]:
        try:
            cmd = ["tail", "-n", str(lines * 2), log_file]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                continue
            entries = []
            for line in r.stdout.splitlines():
                if not line.strip():
                    continue
                lvl = _parse_priority(line)
                if level_filter and level_filter != "all":
                    if LEVEL_MAP.get(lvl, 6) > LEVEL_MAP.get(level_filter, 6):
                        continue
                if grep and grep.lower() not in line.lower():
                    continue
                entries.append({"raw": line, "level": lvl, "source": log_file})
            return {"ok": True, "entries": entries[-lines:], "count": len(entries), "file": log_file}
        except Exception:
            continue
    return {"ok": False, "error": "No syslog file found"}


def get_services():
    """List running systemd services."""
    try:
        r = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=5
        )
        services = []
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if parts:
                services.append(parts[0].replace(".service", ""))
        return services
    except Exception:
        return []


def get_kernel_logs(lines=100):
    """Read dmesg for kernel/hardware events."""
    try:
        r = subprocess.run(
            ["dmesg", "-T", "--level=err,warn,crit,emerg"],
            capture_output=True, text=True, timeout=5
        )
        entries = []
        for line in r.stdout.splitlines()[-lines:]:
            if line.strip():
                entries.append({"raw": line, "level": _parse_priority(line), "source": "dmesg"})
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_ankavm_logs(lines=200):
    """Read ankavm application logs from journald."""
    return get_journal_logs(lines=lines, service="ankavm")


def get_core_dumps():
    """List core dump files."""
    dumps = []
    try:
        r = subprocess.run(
            ["coredumpctl", "list", "--no-pager", "--no-legend"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            if line.strip():
                parts = line.strip().split()
                dumps.append({
                    "raw": line,
                    "pid": parts[1] if len(parts) > 1 else "",
                    "exe": parts[-1] if parts else "",
                })
    except Exception:
        pass
    return dumps






