"""
backup_scheduler.py - ZamanlanmÄ±ÅŸ VM backup yÃ¶netimi.
Schedules: /var/lib/ankavm/backup_schedules.json
History:   /var/log/ankavm/backup_history.jsonl
"""

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False

try:
    import boto3
    _BOTO3_OK = True
except ImportError:
    _BOTO3_OK = False

try:
    import paramiko
    _PARAMIKO_OK = True
except ImportError:
    _PARAMIKO_OK = False

import json
import threading
import time
import uuid
import os
import subprocess
import logging
import io

# SEC-031: FTP backup target is opt-in. Plain-text FTP is deprecated; SFTP is
# the recommended path. Operators that need legacy FTP must set the env var
# ankavm_ENABLE_INSECURE_FTP=1 before service start. ftplib is therefore
# imported lazily so the import alone doesn't pull in plaintext-credential code.
_FTP_ENABLED = os.environ.get("ankavm_ENABLE_INSECURE_FTP") == "1"
if _FTP_ENABLED:
    import ftplib  # noqa: F401  (only imported when explicitly enabled)
else:
    ftplib = None  # type: ignore[assignment]

log = logging.getLogger("ankavm.backup_scheduler")

SCHEDULES_PATH = "/var/lib/ankavm/backup_schedules.json"
HISTORY_PATH   = "/var/log/ankavm/backup_history.jsonl"
_lock          = threading.Lock()
_history_lock  = threading.Lock()


# ---------------------------------------------------------------------------
# Dosya I/O
# ---------------------------------------------------------------------------

def _load():
    """Schedules JSON dosyasÄ±nÄ± yÃ¼kler."""
    try:
        if os.path.exists(SCHEDULES_PATH):
            with open(SCHEDULES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error("_load hatasÄ±: %s", e)
    return {}


def _save(data):
    """Schedules JSON dosyasÄ±nÄ± atomik yazar."""
    try:
        os.makedirs(os.path.dirname(SCHEDULES_PATH), exist_ok=True)
        tmp = SCHEDULES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SCHEDULES_PATH)
    except Exception as e:
        log.error("_save hatasÄ±: %s", e)


# ---------------------------------------------------------------------------
# Cron yardÄ±mcÄ±sÄ±
# ---------------------------------------------------------------------------

def _next_run(cron_expr):
    """
    Sonraki Ã§alÄ±ÅŸma zamanÄ±nÄ± unix timestamp olarak dÃ¶ndÃ¼rÃ¼r.
    croniter yoksa None dÃ¶ndÃ¼rÃ¼r.
    """
    if not CRONITER_AVAILABLE:
        return None
    try:
        it = croniter(cron_expr, time.time())
        return it.get_next(float)
    except Exception as e:
        log.error("_next_run hatasÄ± (expr=%s): %s", cron_expr, e)
        return None


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------

def create_schedule(vm_id, vm_name, cron_expr, retention_count=7,
                    description="", remote_type=None, remote_config=None):
    """
    Yeni backup schedule oluÅŸturur.
    remote_type: "s3" | "ftp" | None
    DÃ¶ner: schedule dict
    """
    try:
        schedule_id = str(uuid.uuid4())
        now         = time.time()
        schedule = {
            "id":              schedule_id,
            "vm_id":           vm_id,
            "vm_name":         vm_name,
            "cron_expr":       cron_expr,
            "retention_count": retention_count,
            "description":     description,
            "remote_type":     remote_type,
            "remote_config":   remote_config or {},
            "created_at":      now,
            "last_run":        None,
            "next_run":        _next_run(cron_expr),
            "enabled":         True,
        }
        with _lock:
            data = _load()
            data[schedule_id] = schedule
            _save(data)
        log.info("create_schedule: vm=%s cron='%s' id=%s", vm_name, cron_expr, schedule_id)
        return schedule
    except Exception as e:
        log.error("create_schedule hatasÄ±: %s", e)
        return {}


def list_schedules():
    """TÃ¼m schedule'larÄ± liste olarak dÃ¶ndÃ¼rÃ¼r."""
    try:
        with _lock:
            data = _load()
        return list(data.values())
    except Exception as e:
        log.error("list_schedules hatasÄ±: %s", e)
        return []


def get_schedule(schedule_id):
    """Tek schedule dÃ¶ndÃ¼rÃ¼r veya None."""
    try:
        with _lock:
            data = _load()
        return data.get(schedule_id)
    except Exception as e:
        log.error("get_schedule hatasÄ±: %s", e)
        return None


def update_schedule(schedule_id, **kwargs):
    """
    Schedule alanlarÄ±nÄ± gÃ¼nceller.
    cron_expr deÄŸiÅŸirse next_run yeniden hesaplanÄ±r.
    """
    try:
        with _lock:
            data = _load()
            if schedule_id not in data:
                return False
            entry = data[schedule_id]
            for k, v in kwargs.items():
                if k in entry:
                    entry[k] = v
            if "cron_expr" in kwargs:
                entry["next_run"] = _next_run(entry["cron_expr"])
            _save(data)
        log.info("update_schedule: %s gÃ¼ncellendi.", schedule_id)
        return True
    except Exception as e:
        log.error("update_schedule hatasÄ±: %s", e)
        return False


def delete_schedule(schedule_id):
    """Schedule'Ä± kalÄ±cÄ± olarak siler."""
    try:
        with _lock:
            data = _load()
            if schedule_id not in data:
                return False
            del data[schedule_id]
            _save(data)
        log.info("delete_schedule: %s silindi.", schedule_id)
        return True
    except Exception as e:
        log.error("delete_schedule hatasÄ±: %s", e)
        return False


# ---------------------------------------------------------------------------
# Backup Ã§alÄ±ÅŸtÄ±rma
# ---------------------------------------------------------------------------

def _run_backup(schedule):
    """
    Verilen schedule iÃ§in:
      1) virsh snapshot-create-as ile snapshot alÄ±r
      2) retention uygulanÄ±r (eski snapshot'lar silinir)
      3) remote_type varsa uzak hedefe yÃ¼kler
    """
    vm_id    = schedule["vm_id"]
    vm_name  = schedule["vm_name"]
    snap_ts  = int(time.time())
    snap_name = f"oxw-backup-{vm_name}-{snap_ts}"

    success = False
    error   = ""

    try:
        # 1. Snapshot oluÅŸtur
        cmd = ["virsh", "snapshot-create-as",
               vm_name, snap_name,
               "--description", f"ankavm auto-backup {snap_ts}",
               "--atomic"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"virsh snapshot-create-as failed: {result.stderr.strip()}")
        log.info("_run_backup: snapshot '%s' oluÅŸturuldu.", snap_name)

        # 2. Retention â€“ eski snapshot'larÄ± listele ve sil
        try:
            ls_out = subprocess.check_output(
                ["virsh", "snapshot-list", vm_name, "--name"],
                stderr=subprocess.DEVNULL, timeout=30
            ).decode("utf-8", errors="replace").strip().splitlines()

            oxw_snaps = sorted(
                [s for s in ls_out if s.startswith("oxw-backup-")],
            )
            retention = schedule.get("retention_count", 7)
            to_delete = oxw_snaps[:-retention] if len(oxw_snaps) > retention else []
            for old_snap in to_delete:
                subprocess.run(
                    ["virsh", "snapshot-delete", vm_name, old_snap],
                    capture_output=True, timeout=60
                )
                log.info("_run_backup: eski snapshot silindi: %s", old_snap)
        except Exception as re:
            log.warning("_run_backup: retention hatasÄ±: %s", re)

        # 3. Remote yÃ¼kleme
        remote_type   = schedule.get("remote_type")
        remote_config = schedule.get("remote_config", {})

        if remote_type == "s3":
            _upload_s3(vm_name, snap_name, remote_config)
        elif remote_type == "ftp":
            _upload_ftp(vm_name, snap_name, remote_config)
        elif remote_type == "sftp":
            _upload_sftp(vm_name, snap_name, remote_config)
        elif remote_type == "ssh":
            _upload_ssh_scp(vm_name, snap_name, remote_config)

        success = True

    except FileNotFoundError:
        error = "virsh bulunamadÄ±"
        log.error("_run_backup: %s", error)
    except Exception as e:
        error = str(e)
        log.error("_run_backup hatasÄ± (vm=%s): %s", vm_name, e)

    _log_history(vm_id, vm_name, snap_name, success, error)
    return success


def _upload_s3(vm_name, snap_name, cfg):
    """boto3 ile S3'e snapshot meta yÃ¼kleme (graceful fallback)."""
    if not _BOTO3_OK:
        log.warning("_upload_s3: boto3 yok, atlanÄ±yor.")
        return
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id     = cfg.get("access_key"),
            aws_secret_access_key = cfg.get("secret_key"),
            region_name           = cfg.get("region", "us-east-1"),
            endpoint_url          = cfg.get("endpoint"),
        )
        bucket  = cfg.get("bucket", "ankavm-backups")
        key     = f"{vm_name}/{snap_name}.json"
        payload = json.dumps({"vm_name": vm_name, "snapshot": snap_name,
                              "ts": time.time()}).encode("utf-8")
        s3.put_object(Bucket=bucket, Key=key, Body=payload)
        log.info("_upload_s3: s3://%s/%s yÃ¼klendi.", bucket, key)
    except Exception as e:
        log.error("_upload_s3 hatasÄ±: %s", e)


def _upload_ftp(vm_name, snap_name, cfg):
    """ftplib ile FTP'ye snapshot meta yÃ¼kleme."""
    try:
        host    = cfg.get("host", "localhost")
        port    = int(cfg.get("port", 21))
        user    = cfg.get("username", "anonymous")
        passwd  = cfg.get("password", "")
        remote_dir = cfg.get("remote_dir", "/")
        filename   = f"{snap_name}.json"
        payload    = json.dumps({"vm_name": vm_name, "snapshot": snap_name,
                                 "ts": time.time()}).encode("utf-8")
        # SEC-031: refuse to use plaintext FTP unless explicitly enabled.
        if not _FTP_ENABLED or ftplib is None:
            log.warning("_upload_ftp: plain-text FTP target attempted but "
                        "ankavm_ENABLE_INSECURE_FTP is not set; aborting and "
                        "recommending SFTP instead.")
            return
        import io
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=30)
        ftp.login(user, passwd)
        try:
            ftp.cwd(remote_dir)
        except Exception:
            pass
        ftp.storbinary(f"STOR {filename}", io.BytesIO(payload))
        ftp.quit()
        log.info("_upload_ftp: ftp://%s/%s/%s yÃ¼klendi.", host, remote_dir, filename)
    except Exception as e:
        log.error("_upload_ftp hatasÄ±: %s", e)


def _upload_sftp(vm_name, snap_name, cfg):
    """
    paramiko ile SFTP Ã¼zerinden backup yÃ¼kleme.
    cfg keys: host, port(22), username, password|private_key_path, remote_dir
    """
    if not _PARAMIKO_OK:
        log.warning("_upload_sftp: paramiko yok. 'pip install paramiko' Ã§alÄ±ÅŸtÄ±rÄ±n.")
        return
    try:
        host       = cfg.get("host", "localhost")
        port       = int(cfg.get("port", 22))
        user       = cfg.get("username", "root")
        passwd     = cfg.get("password", "")
        key_path   = cfg.get("private_key_path", "")
        remote_dir = cfg.get("remote_dir", "/backups")
        filename   = f"{snap_name}.json"
        payload    = json.dumps({
            "vm_name": vm_name, "snapshot": snap_name, "ts": time.time()
        }).encode("utf-8")

        ssh = paramiko.SSHClient()
        # SEC-032: known_hosts + first-contact prompt instead of trust-on-sight.
        try:
            from . import ssh_known_hosts as _kh  # type: ignore
        except Exception:
            import ssh_known_hosts as _kh  # type: ignore
        _hk = _kh.load_known_hosts()
        if _hk is not None:
            ssh._host_keys = _hk
            ssh._host_keys_filename = None
        ssh.set_missing_host_key_policy(_kh.ankavmPolicy())
        if key_path and os.path.isfile(key_path):
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
            ssh.connect(host, port=port, username=user, pkey=pkey, timeout=30)
        else:
            ssh.connect(host, port=port, username=user, password=passwd, timeout=30)

        sftp = ssh.open_sftp()
        # Dizini oluÅŸtur (exist_ok)
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            sftp.mkdir(remote_dir)
        remote_path = remote_dir.rstrip("/") + "/" + filename
        sftp.putfo(io.BytesIO(payload), remote_path)
        sftp.close()
        ssh.close()
        log.info("_upload_sftp: sftp://%s%s yÃ¼klendi.", host, remote_path)
    except Exception as e:
        log.error("_upload_sftp hatasÄ±: %s", e)


def _upload_ssh_scp(vm_name, snap_name, cfg):
    """
    scp (subprocess) ile SSH Ã¼zerinden yÃ¼kleme.
    cfg keys: host, port(22), username, private_key_path, remote_dir
    Parola desteklenmez â€” SSH key kullan.
    """
    try:
        host       = cfg.get("host", "localhost")
        port       = int(cfg.get("port", 22))
        user       = cfg.get("username", "root")
        key_path   = cfg.get("private_key_path", "")
        remote_dir = cfg.get("remote_dir", "/backups")
        filename   = f"{snap_name}.json"
        payload    = json.dumps({
            "vm_name": vm_name, "snapshot": snap_name, "ts": time.time()
        }).encode("utf-8")

        # GeÃ§ici dosyaya yaz
        tmp_path = f"/tmp/{filename}"
        with open(tmp_path, "wb") as f:
            f.write(payload)

        scp_cmd = ["scp", "-P", str(port),
                   "-o", "StrictHostKeyChecking=no",
                   "-o", "BatchMode=yes"]
        if key_path and os.path.isfile(key_path):
            scp_cmd += ["-i", key_path]
        scp_cmd += [tmp_path, f"{user}@{host}:{remote_dir}/{filename}"]

        r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)
        os.unlink(tmp_path)
        if r.returncode == 0:
            log.info("_upload_ssh_scp: %s â†’ %s:%s/%s", filename, host, remote_dir, filename)
        else:
            log.error("_upload_ssh_scp hata: %s", r.stderr.strip())
    except Exception as e:
        log.error("_upload_ssh_scp hatasÄ±: %s", e)


# ---------------------------------------------------------------------------
# History log
# ---------------------------------------------------------------------------

def _log_history(vm_id, vm_name, snapshot_name, success, error=""):
    """JSONL history dosyasÄ±na yeni satÄ±r ekler."""
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        entry = {
            "ts":            time.time(),
            "vm_id":         vm_id,
            "vm_name":       vm_name,
            "snapshot_name": snapshot_name,
            "success":       success,
            "error":         error,
        }
        with _history_lock:
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error("_log_history hatasÄ±: %s", e)


def get_history(vm_id=None, limit=50):
    """
    JSONL history dosyasÄ±ndan kayÄ±tlarÄ± okur.
    vm_id verilirse filtreler. En yeni `limit` kadar dÃ¶ndÃ¼rÃ¼r.
    """
    try:
        if not os.path.exists(HISTORY_PATH):
            return []
        with _history_lock:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()

        records = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if vm_id and rec.get("vm_id") != vm_id:
                    continue
                records.append(rec)
            except Exception:
                pass

        # En yeni Ã¶nce, limit uygula
        records.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return records[:limit]
    except Exception as e:
        log.error("get_history hatasÄ±: %s", e)
        return []


# ---------------------------------------------------------------------------
# Scheduler dÃ¶ngÃ¼sÃ¼
# ---------------------------------------------------------------------------

def check_due():
    """ZamanÄ± gelen (next_run <= now) ve enabled schedule'larÄ± Ã§alÄ±ÅŸtÄ±rÄ±r."""
    try:
        now = time.time()
        with _lock:
            data = _load()

        for schedule_id, schedule in list(data.items()):
            if not schedule.get("enabled", True):
                continue
            next_run = schedule.get("next_run")
            if next_run is None:
                continue
            if now < next_run:
                continue

            # Yeni next_run hesapla (Ã§alÄ±ÅŸtÄ±rmadan Ã¶nce kaydet)
            new_next = _next_run(schedule["cron_expr"])
            with _lock:
                fresh = _load()
                if schedule_id in fresh:
                    fresh[schedule_id]["last_run"]  = now
                    fresh[schedule_id]["next_run"]  = new_next
                    _save(fresh)

            # Backup'Ä± ayrÄ± thread'de Ã§alÄ±ÅŸtÄ±r
            t = threading.Thread(
                target=_run_backup,
                args=(schedule,),
                name=f"backup-{schedule_id[:8]}",
                daemon=True,
            )
            t.start()
            log.info("check_due: schedule %s tetiklendi (vm=%s).",
                     schedule_id, schedule.get("vm_name"))

    except Exception as e:
        log.error("check_due hatasÄ±: %s", e)


def start_scheduler():
    """
    Daemon thread baÅŸlatÄ±r; her 30 saniyede check_due Ã§aÄŸÄ±rÄ±r.
    """
    def _loop():
        log.info("backup_scheduler baÅŸladÄ±.")
        while True:
            try:
                check_due()
            except Exception as e:
                log.error("Scheduler dÃ¶ngÃ¼sÃ¼ hatasÄ±: %s", e)
            time.sleep(30)

    t = threading.Thread(target=_loop, name="backup-scheduler", daemon=True)
    t.start()
    log.info("backup_scheduler thread baÅŸlatÄ±ldÄ±.")
    return t


def trigger_now(schedule_id):
    """
    Belirtilen schedule'Ä± elle tetikler.
    DÃ¶ner: True (baÅŸarÄ±) / False (bulunamadÄ± veya hata)
    """
    try:
        with _lock:
            data = _load()
        schedule = data.get(schedule_id)
        if not schedule:
            log.warning("trigger_now: schedule bulunamadÄ± (%s).", schedule_id)
            return False

        t = threading.Thread(
            target=_run_backup,
            args=(schedule,),
            name=f"backup-manual-{schedule_id[:8]}",
            daemon=True,
        )
        t.start()
        log.info("trigger_now: %s manuel tetiklendi.", schedule_id)
        return True
    except Exception as e:
        log.error("trigger_now hatasÄ±: %s", e)
        return False






