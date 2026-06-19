"""
ankavm GÃ¼ncelleme Sistemi
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GitHub Ã¼zerinden otomatik gÃ¼ncelleme:
  - Uzak repo ile yerel commit karÅŸÄ±laÅŸtÄ±rmasÄ±
  - Yeni dosyalarÄ± ve deÄŸiÅŸiklikleri listele
  - git pull ile uygula, servisi yeniden baÅŸlat
"""

import os
import json
import subprocess
import requests
import logging
import time
import threading
from datetime import datetime

log = logging.getLogger("ankavm.updater")

UPDATE_CONFIG_FILE = os.environ.get("ankavm_UPDATE_CONFIG", "/etc/ankavm/update.conf")
UPDATE_LOG_FILE    = os.path.join(os.environ.get("ankavm_LOG_DIR", "/var/log/ankavm"), "updates.jsonl")

# â”€â”€ KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

DEFAULT_REPO_URL = "https://github.com/ShinnAsukha/ankavm-hypervisor"
DEFAULT_BRANCH   = "main"


def _load_config() -> dict:
    defaults = {
        "repo_url":   DEFAULT_REPO_URL,
        "branch":     DEFAULT_BRANCH,
        "auto_check": "false",
        "project_dir": _detect_project_dir(),
    }
    if not os.path.exists(UPDATE_CONFIG_FILE):
        # Ä°lk kurulum: config dosyasÄ± yoksa varsayÄ±lanlarÄ± yaz
        _write_config(DEFAULT_REPO_URL, DEFAULT_BRANCH, False)
        return defaults
    try:
        cfg = {}
        for line in open(UPDATE_CONFIG_FILE):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip().lower()] = v.strip()
        merged = {**defaults, **cfg}
        # BoÅŸ repo_url varsa (eski kurulum) default'a dÃ¼ÅŸÃ¼r
        if not merged.get("repo_url"):
            merged["repo_url"] = DEFAULT_REPO_URL
        if not merged.get("branch"):
            merged["branch"] = DEFAULT_BRANCH
        return merged
    except Exception:
        return defaults


def _write_config(repo_url: str, branch: str, auto_check: bool):
    os.makedirs(os.path.dirname(UPDATE_CONFIG_FILE), exist_ok=True)
    lines = [
        "# ankavm GÃ¼ncelleme YapÄ±landÄ±rmasÄ±",
        f"REPO_URL    = {repo_url}",
        f"BRANCH      = {branch}",
        f"AUTO_CHECK  = {'true' if auto_check else 'false'}",
        f"PROJECT_DIR = {_detect_project_dir()}",
    ]
    with open(UPDATE_CONFIG_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(UPDATE_CONFIG_FILE, 0o600)


def save_config(repo_url: str = DEFAULT_REPO_URL, branch: str = DEFAULT_BRANCH,
                auto_check: bool = False):
    _write_config(repo_url, branch, auto_check)


def _detect_project_dir() -> str:
    """ankavm proje kÃ¶k dizinini bul."""
    this_file = os.path.abspath(__file__)
    # backend/updater.py â†’ ankavm/
    return os.path.dirname(os.path.dirname(os.path.dirname(this_file)))


# â”€â”€ Git Ä°ÅŸlemleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _run(cmd: list, cwd: str = None) -> tuple[int, str, str]:
    """Komutu Ã§alÄ±ÅŸtÄ±r, (returncode, stdout, stderr) dÃ¶ndÃ¼r."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=60
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Zaman aÅŸÄ±mÄ±"
    except Exception as e:
        return -1, "", str(e)


def _is_git_repo(path: str) -> bool:
    code, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0


def _local_commit(path: str) -> str:
    _, out, _ = _run(["git", "rev-parse", "HEAD"], cwd=path)
    return out[:40] if out else ""


def _local_branch(path: str) -> str:
    _, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    return out or "main"


def _ensure_remote(path: str, repo_url: str):
    """Remote 'origin' yoksa ekle, varsa gÃ¼ncelle."""
    code, out, _ = _run(["git", "remote", "get-url", "origin"], cwd=path)
    if code != 0:
        _run(["git", "remote", "add", "origin", repo_url], cwd=path)
    elif out != repo_url:
        _run(["git", "remote", "set-url", "origin", repo_url], cwd=path)


def _init_repo_if_needed(path: str, repo_url: str, branch: str):
    """Git repo yoksa baÅŸlat ve remote baÄŸla."""
    if not _is_git_repo(path):
        _run(["git", "init", "-b", branch], cwd=path)
        _run(["git", "remote", "add", "origin", repo_url], cwd=path)
    else:
        _ensure_remote(path, repo_url)


# â”€â”€ GitHub API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _github_api_url(repo_url: str) -> str:
    """https://github.com/user/repo â†’ https://api.github.com/repos/user/repo"""
    url = repo_url.rstrip("/").replace("https://github.com/", "")
    url = url.replace("http://github.com/", "")
    if url.endswith(".git"):
        url = url[:-4]
    return f"https://api.github.com/repos/{url}"


def _get_remote_commits(repo_url: str, branch: str, limit: int = 20) -> list | tuple:
    """
    GitHub API Ã¼zerinden son commit'leri Ã§ek.
    BaÅŸarÄ±: list of commit dicts
    Hata:   (str,) â€” hata mesajÄ± iÃ§eren tek elemanlÄ± tuple
    """
    api_url = _github_api_url(repo_url) + f"/commits?sha={branch}&per_page={limit}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(api_url, timeout=10, headers=headers)
        if r.status_code == 200:
            commits = r.json()
            return [
                {
                    "sha":      c["sha"][:8],
                    "sha_full": c["sha"],
                    "message":  c["commit"]["message"].split("\n")[0][:100],
                    "author":   c["commit"]["author"]["name"],
                    "date":     c["commit"]["author"]["date"],
                }
                for c in commits
            ]
        elif r.status_code == 403:
            reset_ts = r.headers.get("X-RateLimit-Reset", "")
            if r.headers.get("X-RateLimit-Remaining") == "0":
                from datetime import datetime
                try:
                    reset_str = datetime.fromtimestamp(int(reset_ts)).strftime("%H:%M")
                except Exception:
                    reset_str = reset_ts
                return (f"GitHub API rate limit doldu. SÄ±fÄ±rlanma: {reset_str}. "
                        "1 saat sonra tekrar deneyin.",)
            return ("GitHub eriÅŸim reddedildi (403).",)
        elif r.status_code == 404:
            return ("Repo bulunamadÄ± (404). URL ve branch adÄ±nÄ± kontrol edin.",)
        else:
            return (f"GitHub API beklenmedik yanÄ±t: HTTP {r.status_code}",)
    except requests.exceptions.ConnectionError:
        return ("GitHub'a baÄŸlanÄ±lamadÄ±. Sunucunun internet eriÅŸimini kontrol edin.",)
    except requests.exceptions.Timeout:
        return ("GitHub API zaman aÅŸÄ±mÄ± (10s). AÄŸ baÄŸlantÄ±sÄ± yavaÅŸ veya kesik.",)
    except Exception as e:
        log.error("GitHub API hatasÄ±: %s", e)
        return (f"GitHub API hatasÄ±: {e}",)


def _get_remote_head(repo_url: str, branch: str) -> str:
    """GitHub API Ã¼zerinden en son commit SHA'sÄ±nÄ± al."""
    commits = _get_remote_commits(repo_url, branch, limit=1)
    if isinstance(commits, list) and commits:
        return commits[0]["sha_full"]
    return ""


# â”€â”€ Ana Fonksiyonlar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def check_updates() -> dict:
    """
    GÃ¼ncelleme kontrolÃ¼ yap.
    DÃ¶nÃ¼ÅŸ: {up_to_date, current_sha, remote_sha, new_commits, error}
    """
    cfg = _load_config()
    repo_url = cfg.get("repo_url", DEFAULT_REPO_URL)
    branch   = cfg.get("branch", DEFAULT_BRANCH)
    proj_dir = cfg.get("project_dir", _detect_project_dir())

    if not repo_url:
        return {"error": "Repo URL ayarlanmamÄ±ÅŸ. Ayarlar â†’ GÃ¼ncellemeler bÃ¶lÃ¼mÃ¼nden girin."}

    # Yerel commit
    local_sha = ""
    if _is_git_repo(proj_dir):
        local_sha = _local_commit(proj_dir)

    # Uzak commit'leri Ã§ek â€” branch yanlÄ±ÅŸsa default branch'i dene
    remote_commits = _get_remote_commits(repo_url, branch)
    if isinstance(remote_commits, tuple):
        err_msg = remote_commits[0]
        # 404 + branch hatasÄ± olabilir: default branch'i Ã¶ÄŸren ve tekrar dene
        if "404" in err_msg or "bulunamadÄ±" in err_msg:
            real_branch = _detect_default_branch(repo_url)
            if real_branch != branch:
                remote_commits2 = _get_remote_commits(repo_url, real_branch)
                if isinstance(remote_commits2, list) and remote_commits2:
                    remote_commits = remote_commits2
                    branch = real_branch
                    log.warning("check_updates: branch '%s' â†’ '%s' otomatik dÃ¼zeltildi.",
                                cfg.get("branch"), branch)
                else:
                    return {"error": err_msg}
            else:
                return {"error": err_msg}
        else:
            return {"error": err_msg}
    if not remote_commits:
        return {"error": "GitHub'a baÄŸlanÄ±lamadÄ± veya repo bulunamadÄ±."}

    remote_sha = remote_commits[0]["sha_full"]

    # Yeni commit'leri bul
    new_commits = []
    if local_sha:
        for c in remote_commits:
            if c["sha_full"].startswith(local_sha[:8]) or local_sha.startswith(c["sha_full"][:8]):
                break
            new_commits.append(c)
    else:
        new_commits = remote_commits

    return {
        "up_to_date":     len(new_commits) == 0,
        "current_sha":    local_sha[:8] if local_sha else "bilinmiyor",
        "remote_sha":     remote_sha[:8],
        "new_commits":    new_commits,
        "new_count":      len(new_commits),
        "repo_url":       repo_url,
        "branch":         branch,
        "checked_at":     datetime.now().isoformat(),
    }


def _detect_default_branch(repo_url: str) -> str:
    """GitHub API'den repo'nun default branch'ini al. BaÅŸarÄ±sÄ±z â†’ 'main'."""
    try:
        api_url = _github_api_url(repo_url)
        headers = {"Accept": "application/vnd.github.v3+json"}
        r = requests.get(api_url, timeout=8, headers=headers)
        if r.status_code == 200:
            return r.json().get("default_branch", DEFAULT_BRANCH)
    except Exception:
        pass
    return DEFAULT_BRANCH


def apply_update() -> dict:
    """
    GÃ¼ncellemeyi uygula: git pull Ã§ek, servisi yeniden baÅŸlat.
    """
    cfg      = _load_config()
    repo_url = cfg.get("repo_url", DEFAULT_REPO_URL)
    branch   = cfg.get("branch", DEFAULT_BRANCH)
    proj_dir = cfg.get("project_dir", _detect_project_dir())

    if not repo_url:
        return {"success": False, "error": "Repo URL ayarlanmamÄ±ÅŸ."}

    log.info("GÃ¼ncelleme baÅŸlatÄ±lÄ±yor: %s @ %s", repo_url, branch)
    steps = []

    try:
        # 1. Git repo yoksa baÅŸlat
        _init_repo_if_needed(proj_dir, repo_url, branch)
        steps.append({"step": "repo_init", "status": "ok"})

        # 2. Fetch â€” branch bulunamazsa GitHub'dan default branch'i Ã¶ÄŸren ve tekrar dene
        code, out, err = _run(["git", "fetch", "origin", branch], cwd=proj_dir)
        if code != 0:
            if "couldn't find remote ref" in err or "invalid refspec" in err.lower():
                # Branch adÄ± yanlÄ±ÅŸ â€” GitHub API'den gerÃ§ek default branch'i al
                real_branch = _detect_default_branch(repo_url)
                log.warning("Branch '%s' bulunamadÄ±, '%s' deneniyor.", branch, real_branch)
                if real_branch != branch:
                    code2, out2, err2 = _run(
                        ["git", "fetch", "origin", real_branch], cwd=proj_dir
                    )
                    if code2 == 0:
                        branch = real_branch   # geri kalan adÄ±mlar iÃ§in gÃ¼ncelle
                        steps.append({"step": "branch_autofix",
                                      "status": "warning",
                                      "detail": f"Branch '{cfg.get('branch')}' yerine '{branch}' kullanÄ±ldÄ±. Ayarlar â†’ GÃ¼ncellemeler'den dÃ¼zeltin."})
                    else:
                        return {"success": False,
                                "error": (f"Branch '{cfg.get('branch')}' bulunamadÄ± ve "
                                          f"'{real_branch}' da baÅŸarÄ±sÄ±z: {err2}. "
                                          "Ayarlar â†’ GÃ¼ncellemeler â†’ Branch alanÄ±nÄ± kontrol edin."),
                                "steps": steps}
                else:
                    return {"success": False,
                            "error": (f"Branch '{branch}' GitHub'da bulunamadÄ±: {err}. "
                                      "Ayarlar â†’ GÃ¼ncellemeler â†’ Branch alanÄ±nÄ± dÃ¼zeltin "
                                      "(Ã¶rn. 'main' veya 'master')."),
                            "steps": steps}
            else:
                return {"success": False, "error": f"git fetch baÅŸarÄ±sÄ±z: {err}", "steps": steps}
        steps.append({"step": "fetch", "status": "ok"})

        # 3. Mevcut SHA
        old_sha = _local_commit(proj_dir)

        # 4. Reset â€” yerel deÄŸiÅŸiklikleri atla, uzak branch'e zorla al
        code, out, err = _run(
            ["git", "reset", "--hard", f"origin/{branch}"], cwd=proj_dir
        )
        if code != 0:
            return {"success": False, "error": f"git reset baÅŸarÄ±sÄ±z: {err}", "steps": steps}
        steps.append({"step": "reset", "status": "ok"})

        # 5. Yeni SHA
        new_sha = _local_commit(proj_dir)
        steps.append({"step": "update", "status": "ok", "old_sha": old_sha[:8], "new_sha": new_sha[:8]})

        # 6. Python baÄŸÄ±mlÄ±lÄ±klarÄ± gÃ¼ncelle
        venv_pip = "/opt/ankavm/venv/bin/pip"
        req_file = os.path.join(proj_dir, "ankavm", "backend", "requirements.txt")
        if os.path.exists(venv_pip) and os.path.exists(req_file):
            code, out, err = _run([venv_pip, "install", "-r", req_file, "-q"], cwd=proj_dir)
            steps.append({"step": "pip_install", "status": "ok" if code == 0 else "warning", "detail": err[:200] if err else ""})

        # 7. GÃ¼ncelleme loguna kaydet
        _log_update(old_sha, new_sha, repo_url, branch, steps)

        # 8. Servisi arka planda yeniden baÅŸlat (5 sn gecikme â†’ yanÄ±t dÃ¶nebilsin)
        def _restart():
            time.sleep(5)
            subprocess.run(["systemctl", "restart", "ankavm"], timeout=30)

        import threading
        threading.Thread(target=_restart, daemon=True).start()
        steps.append({"step": "restart_scheduled", "status": "ok"})

        return {
            "success":  True,
            "old_sha":  old_sha[:8] if old_sha else "â€”",
            "new_sha":  new_sha[:8],
            "steps":    steps,
            "message":  "GÃ¼ncelleme uygulandÄ±. Servis 5 saniye iÃ§inde yeniden baÅŸlayacak.",
        }

    except Exception as e:
        log.error("GÃ¼ncelleme hatasÄ±: %s", e)
        return {"success": False, "error": str(e), "steps": steps}


def get_update_history(limit: int = 20) -> list:
    """GeÃ§miÅŸ gÃ¼ncelleme kayÄ±tlarÄ±nÄ± dÃ¶ndÃ¼r."""
    if not os.path.exists(UPDATE_LOG_FILE):
        return []
    entries = []
    with open(UPDATE_LOG_FILE) as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass
    return sorted(entries, key=lambda x: x.get("timestamp", 0), reverse=True)[:limit]


def get_config() -> dict:
    cfg = _load_config()
    return {
        "repo_url":    cfg.get("repo_url", DEFAULT_REPO_URL),
        "branch":      cfg.get("branch", DEFAULT_BRANCH),
        "auto_check":  cfg.get("auto_check", "false").lower() == "true",
        "project_dir": cfg.get("project_dir", ""),
        "is_git_repo": _is_git_repo(cfg.get("project_dir", _detect_project_dir())),
        "local_sha":   _local_commit(cfg.get("project_dir", _detect_project_dir()))[:8],
    }


# â”€â”€ AI Analiz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Son kontrol sonucu â€” frontend polling iÃ§in bellekte tutulur
_last_check_result: dict = {}
_last_ai_analysis: str   = ""
_check_lock = threading.Lock()

def _ai_analyze_commits(commits: list) -> str:
    """
    Yeni commit listesini yapÄ±landÄ±rÄ±lmÄ±ÅŸ AI ajanÄ±na gÃ¶nderir,
    TÃ¼rkÃ§e kÄ±sa Ã¶zet dÃ¶ndÃ¼rÃ¼r.
    HiÃ§bir AI ajanÄ± yoksa basit metin Ã¶zeti dÃ¶ner.
    """
    if not commits:
        return ""
    commit_text = "\n".join(
        f"- [{c['sha']}] {c['message']} ({c['author']}, {c['date'][:10]})"
        for c in commits[:15]
    )
    prompt = (
        f"AÅŸaÄŸÄ±daki {len(commits)} yeni GitHub commit'ini analiz et. "
        "Her commit'in ne deÄŸiÅŸtirdiÄŸini, potansiyel riskleri ve "
        "sistem yÃ¶neticisinin dikkat etmesi gerekenleri TÃ¼rkÃ§e, "
        "kÄ±sa madde madde Ã¶zetle:\n\n" + commit_text
    )
    try:
        import ai_agent
        cfg = ai_agent._load_ai_config()
        agents = cfg.get("agents", {})
        # Aktif ilk ajanÄ± bul
        active_id = next(
            (aid for aid, a in agents.items() if a.get("enabled", True) and a.get("api_key")),
            None
        )
        if active_id:
            return ai_agent.query_agent(active_id, prompt,
                system_prompt="Sen bir Linux sistem yÃ¶neticisi asistanÄ±sÄ±n. Teknik ve kÄ±sa cevap ver.")
    except Exception as e:
        log.warning("AI analiz hatasÄ±: %s", e)

    # Fallback: basit metin Ã¶zeti
    lines = [f"â€¢ [{c['sha']}] {c['message']}" for c in commits[:10]]
    return f"{len(commits)} yeni commit bulundu:\n" + "\n".join(lines)


def check_updates_with_ai() -> dict:
    """
    GÃ¼ncelleme kontrolÃ¼ yap + AI ile commit Ã¶zetini Ã¼ret.
    Sonucu _last_check_result'a yaz.
    """
    result = check_updates()
    result["ai_analysis"] = ""
    if result.get("new_commits"):
        result["ai_analysis"] = _ai_analyze_commits(result["new_commits"])
    with _check_lock:
        global _last_check_result, _last_ai_analysis
        _last_check_result = result
        _last_ai_analysis  = result.get("ai_analysis", "")
    log.info("GÃ¼ncelleme kontrolÃ¼ tamamlandÄ±. Yeni: %d", result.get("new_count", 0))
    return result


def get_last_check() -> dict:
    """Son kontrol sonucunu dÃ¶ndÃ¼r (bellekten, API polling iÃ§in)."""
    with _check_lock:
        return dict(_last_check_result)


# â”€â”€ Saatlik Scheduler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_scheduler_started = False

def start_auto_check(interval_seconds: int = 3600):
    """
    Daemon thread baÅŸlatÄ±r. Her `interval_seconds`'da bir
    check_updates_with_ai() Ã§aÄŸÄ±rÄ±r ve badge iÃ§in event yazar.
    """
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        log.info("GÃ¼ncelleme otomatik kontrol baÅŸladÄ± (her %ds).", interval_seconds)
        # Ä°lk kontrol baÅŸlamadan Ã¶nce 30 sn bekle (sistem startup'Ä±nÄ± tamamlasÄ±n)
        time.sleep(30)
        while True:
            try:
                cfg = _load_config()
                if cfg.get("repo_url"):
                    result = check_updates_with_ai()
                    count  = result.get("new_count", 0)
                    if count > 0:
                        try:
                            import event_logger as ev
                            ev.warn(
                                f"GÃ¼ncelleme mevcut: {count} yeni commit. "
                                f"AI Ã–zeti: {result.get('ai_analysis','')[:200]}",
                                category="update"
                            )
                        except Exception:
                            pass
                else:
                    log.debug("Repo URL ayarlanmamÄ±ÅŸ, gÃ¼ncelleme kontrolÃ¼ atlanÄ±yor.")
            except Exception as e:
                log.error("Otomatik gÃ¼ncelleme kontrolÃ¼ hatasÄ±: %s", e)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="update-auto-check", daemon=True)
    t.start()
    log.info("GÃ¼ncelleme otomatik kontrol thread'i baÅŸlatÄ±ldÄ±.")
    return t


def _log_update(old_sha: str, new_sha: str, repo_url: str, branch: str, steps: list):
    os.makedirs(os.path.dirname(UPDATE_LOG_FILE), exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "datetime":  datetime.now().isoformat(),
        "old_sha":   old_sha[:8] if old_sha else "",
        "new_sha":   new_sha[:8] if new_sha else "",
        "repo_url":  repo_url,
        "branch":    branch,
        "steps":     steps,
    }
    with open(UPDATE_LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")






