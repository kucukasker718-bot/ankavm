"""
ankavm Predictive Failure Analysis
──────────────────────────────────
SMART disk + ECC RAM + thermal + uptime → arıza tahmini.

API:
    scan_all_disks() -> list
    get_disk_health(device) -> dict
    get_predictions() -> list  (risk skorlu liste)
"""

import subprocess, json, logging, time
from pathlib import Path

log = logging.getLogger("predictive_failure")


def _smartctl_info(device: str) -> dict:
    try:
        r = subprocess.run(
            ["smartctl", "-A", "-i", "-H", "--json=c", device],
            capture_output=True, text=True, timeout=15
        )
        if r.stdout:
            return json.loads(r.stdout)
    except Exception as e:
        log.debug("smartctl error %s: %s", device, e)
    return {}


def get_disk_health(device: str) -> dict:
    data = _smartctl_info(device)
    if not data:
        return {"device": device, "available": False}

    smart = data.get("smart_status", {})
    health_ok = smart.get("passed", None)

    attrs = {}
    for a in data.get("ata_smart_attributes", {}).get("table", []):
        attrs[a.get("name", "")] = {
            "value": a.get("value"),
            "worst": a.get("worst"),
            "thresh": a.get("thresh"),
            "raw":   a.get("raw", {}).get("value"),
        }

    # Risk score: critical attrs
    risk = 0
    risk_reasons = []
    crit = ["Reallocated_Sector_Ct", "Current_Pending_Sector",
            "Offline_Uncorrectable", "UDMA_CRC_Error_Count",
            "Reported_Uncorrect", "Wear_Leveling_Count"]
    for k in crit:
        if k in attrs:
            raw = attrs[k].get("raw", 0) or 0
            if raw > 0:
                risk += min(raw * 10, 50)
                risk_reasons.append(f"{k}={raw}")
    # Temperature
    temp = attrs.get("Temperature_Celsius", {}).get("raw", 0) or 0
    if isinstance(temp, int) and temp > 55:
        risk += (temp - 55) * 3
        risk_reasons.append(f"high_temp={temp}C")

    if not health_ok and health_ok is False:
        risk += 80
        risk_reasons.append("SMART_health_FAIL")

    return {
        "device":      device,
        "available":   True,
        "model":       data.get("model_name", "?"),
        "serial":      data.get("serial_number", "?"),
        "capacity_gb": (data.get("user_capacity", {}).get("bytes", 0) or 0) // (1024**3),
        "health":      "OK" if health_ok else ("FAIL" if health_ok is False else "?"),
        "temperature": temp,
        "risk_score":  min(risk, 100),
        "risk_level":  "critical" if risk > 75 else "high" if risk > 40 else "medium" if risk > 15 else "low",
        "reasons":     risk_reasons,
        "power_on_hours": attrs.get("Power_On_Hours", {}).get("raw", 0),
    }


def scan_all_disks() -> list:
    try:
        r = subprocess.run(["lsblk", "-d", "-n", "-o", "NAME,TYPE"],
                           capture_output=True, text=True, timeout=5)
        disks = []
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "disk":
                disks.append(f"/dev/{parts[0]}")
        return [get_disk_health(d) for d in disks]
    except Exception as e:
        log.warning("scan_all_disks: %s", e)
        return []


def get_predictions(threshold: int = 40) -> list:
    """Risk skoru threshold'un üstündeki diskler."""
    results = scan_all_disks()
    risky = [r for r in results
             if r.get("available") and r.get("risk_score", 0) >= threshold]
    return sorted(risky, key=lambda x: x["risk_score"], reverse=True)


def get_summary() -> dict:
    disks = scan_all_disks()
    available = [d for d in disks if d.get("available")]
    return {
        "total":    len(disks),
        "available": len(available),
        "ok":       sum(1 for d in available if d.get("risk_level") == "low"),
        "warning":  sum(1 for d in available if d.get("risk_level") in ("medium", "high")),
        "critical": sum(1 for d in available if d.get("risk_level") == "critical"),
        "disks":    available,
    }






