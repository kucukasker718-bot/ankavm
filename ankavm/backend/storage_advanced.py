"""
ankavm Storage Advanced — Dedup, Tiering, SPBM, iSCSI
─────────────────────────────────────────────────────
ZFS/btrfs dedup + storage tier policy + iSCSI target/initiator + SPBM.

API: dedup_status, tier_policy_*, iscsi_*, spbm_*
"""

import subprocess, json, logging
from pathlib import Path

log = logging.getLogger("storage_advanced")

_TIER_POLICY = Path("/var/lib/ankavm/storage_tiers.json")
_SPBM_POLICY = Path("/var/lib/ankavm/spbm_policies.json")


# ── ZFS Dedup + Compression ─────────────────────────────────────────────────
def zfs_pools() -> list:
    try:
        r = subprocess.run(["zpool", "list", "-H", "-o",
                            "name,size,alloc,free,dedupratio,compratio,health"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 7:
                out.append({
                    "name":       parts[0],
                    "size":       parts[1],
                    "allocated":  parts[2],
                    "free":       parts[3],
                    "dedup_ratio": parts[4],
                    "compress_ratio": parts[5],
                    "health":     parts[6],
                })
        return out
    except FileNotFoundError:
        return []
    except Exception:
        return []


def zfs_set_property(dataset: str, prop: str, value: str) -> dict:
    """zfs set dedup=on|off compress=lz4|zstd"""
    allowed = {"dedup", "compression", "atime", "sync", "recordsize", "quota"}
    if prop not in allowed:
        return {"ok": False, "error": f"İzin verilmeyen property: {prop}"}
    try:
        r = subprocess.run(["zfs", "set", f"{prop}={value}", dataset],
                           capture_output=True, text=True, timeout=10)
        return {"ok": r.returncode == 0, "dataset": dataset,
                "prop": prop, "value": value, "stderr": r.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def btrfs_dedup_status() -> dict:
    """duperemove / btrfs-dedupe çıktısı — minimal."""
    try:
        r = subprocess.run(["btrfs", "filesystem", "show"],
                           capture_output=True, text=True, timeout=10)
        return {"available": r.returncode == 0,
                "filesystems": r.stdout if r.returncode == 0 else ""}
    except FileNotFoundError:
        return {"available": False, "error": "btrfs yok"}
    except Exception as e:
        return {"available": False, "error": str(e)}


# ── Storage Tier Policy ─────────────────────────────────────────────────────
def list_tier_policies() -> list:
    if not _TIER_POLICY.exists():
        return _default_tiers()
    try:
        return json.loads(_TIER_POLICY.read_text())
    except Exception:
        return _default_tiers()


def _default_tiers() -> list:
    return [
        {"name": "hot",  "description": "SSD/NVMe — kritik VM'ler", "pools": [], "priority": 1},
        {"name": "warm", "description": "SATA SSD — orta öncelik",  "pools": [], "priority": 2},
        {"name": "cold", "description": "HDD — arşiv, backup",      "pools": [], "priority": 3},
    ]


def save_tier_policies(tiers: list) -> dict:
    _TIER_POLICY.parent.mkdir(parents=True, exist_ok=True)
    _TIER_POLICY.write_text(json.dumps(tiers, indent=2, ensure_ascii=False))
    return {"ok": True, "count": len(tiers)}


def assign_pool_to_tier(pool_name: str, tier_name: str) -> dict:
    tiers = list_tier_policies()
    # Önce diğer tier'lardan çıkar
    for t in tiers:
        if pool_name in t["pools"]:
            t["pools"].remove(pool_name)
    # Yeni tier'a ekle
    target = next((t for t in tiers if t["name"] == tier_name), None)
    if not target:
        return {"ok": False, "error": f"Tier yok: {tier_name}"}
    target["pools"].append(pool_name)
    save_tier_policies(tiers)
    return {"ok": True, "pool": pool_name, "tier": tier_name}


# ── SPBM (Storage Policy Based Management) ──────────────────────────────────
def list_spbm_policies() -> list:
    if not _SPBM_POLICY.exists():
        return _default_spbm()
    try:
        return json.loads(_SPBM_POLICY.read_text())
    except Exception:
        return _default_spbm()


def _default_spbm() -> list:
    return [
        {
            "name":        "tier-1-production",
            "description": "Yüksek performans + günlük yedek + 3 snapshot",
            "tier":        "hot",
            "iops_min":    5000,
            "thin_provision": False,
            "backup_freq": "daily",
            "snapshots":   3,
            "tags":        ["production", "critical"],
        },
        {
            "name":        "tier-2-staging",
            "description": "Orta performans + haftalık yedek",
            "tier":        "warm",
            "iops_min":    1000,
            "thin_provision": True,
            "backup_freq": "weekly",
            "snapshots":   1,
            "tags":        ["staging"],
        },
        {
            "name":        "tier-3-dev",
            "description": "Ekonomik + yedeksiz",
            "tier":        "cold",
            "iops_min":    100,
            "thin_provision": True,
            "backup_freq": "none",
            "snapshots":   0,
            "tags":        ["dev", "test"],
        },
    ]


def save_spbm_policies(policies: list) -> dict:
    _SPBM_POLICY.parent.mkdir(parents=True, exist_ok=True)
    _SPBM_POLICY.write_text(json.dumps(policies, indent=2, ensure_ascii=False))
    return {"ok": True, "count": len(policies)}


def select_pool_for_policy(policy_name: str) -> dict:
    """Policy'ye göre uygun pool öner (en boş + uygun tier)."""
    policy = next((p for p in list_spbm_policies() if p["name"] == policy_name), None)
    if not policy:
        return {"ok": False, "error": f"Policy yok: {policy_name}"}
    tier = policy.get("tier")
    tier_pools = []
    for t in list_tier_policies():
        if t["name"] == tier:
            tier_pools = t["pools"]
            break
    if not tier_pools:
        return {"ok": False, "error": f"Tier '{tier}' için pool atanmamış"}
    return {"ok": True, "policy": policy_name, "tier": tier,
            "candidate_pools": tier_pools,
            "suggestion": tier_pools[0]}


# ── iSCSI Target/Initiator ──────────────────────────────────────────────────
def iscsi_initiator_sessions() -> list:
    """Mevcut iSCSI bağlantılarını listele."""
    try:
        r = subprocess.run(["iscsiadm", "-m", "session"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return []
        out = []
        for line in r.stdout.splitlines():
            # tcp: [1] 192.168.1.100:3260,1 iqn.... (non-flash)
            parts = line.split()
            if len(parts) >= 4:
                out.append({"transport": parts[0].rstrip(":"),
                            "session_id": parts[1].strip("[]"),
                            "target":     parts[2],
                            "iqn":        parts[3]})
        return out
    except FileNotFoundError:
        return []
    except Exception:
        return []


def iscsi_discover(portal: str, port: int = 3260) -> list:
    """iscsiadm discovery."""
    try:
        r = subprocess.run(
            ["iscsiadm", "-m", "discovery", "-t", "sendtargets",
             "-p", f"{portal}:{port}"],
            capture_output=True, text=True, timeout=15
        )
        out = []
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                out.append({"target": parts[0], "iqn": parts[1]})
        return out
    except Exception as e:
        return [{"error": str(e)}]


def iscsi_login(portal: str, iqn: str) -> dict:
    try:
        r = subprocess.run(
            ["iscsiadm", "-m", "node", "-p", portal, "-T", iqn, "--login"],
            capture_output=True, text=True, timeout=15
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout,
                "stderr": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def iscsi_target_status() -> dict:
    """LIO/tgtd target servisi çalışıyor mu."""
    out = {"tgtd": False, "lio": False}
    try:
        r = subprocess.run(["systemctl", "is-active", "tgt"],
                           capture_output=True, text=True, timeout=3)
        out["tgtd"] = r.stdout.strip() == "active"
    except Exception:
        pass
    try:
        r = subprocess.run(["systemctl", "is-active", "target"],
                           capture_output=True, text=True, timeout=3)
        out["lio"] = r.stdout.strip() == "active"
    except Exception:
        pass
    return out






