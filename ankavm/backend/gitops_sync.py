"""
gitops_sync.py — GitOps Sync (ArgoCD / Flux) for ankavm
ankavm v2.5.10 Cloud/K8s

Features:
  - configure_gitops(repo_url, branch, path, provider, ssh_key) — save GitOps config
  - get_config() — return current GitOps configuration
  - sync_now() — git pull + YAML diff + apply (manifest-based, no external Git lib)
  - get_sync_status() — last sync result, last commit, diff summary
  - generate_app_manifest() — ArgoCD Application or Flux GitRepository + Kustomization YAML

Config persisted to /var/lib/ankavm/gitops.json
No external dependencies (stdlib + subprocess only). No periodic background jobs.
"""

from __future__ import annotations
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("gitops_sync")

_CONFIG_FILE  = Path("/var/lib/ankavm/gitops.json")
_SYNC_DIR     = Path("/var/lib/ankavm/gitops_repo")
_lock         = threading.Lock()

_VALID_PROVIDERS = ("argocd", "flux")


# ── Persistent store ──────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("gitops load fail: %s", e)
    return {
        "configured": False,
        "repo_url":   None,
        "branch":     "main",
        "path":       ".",
        "provider":   "argocd",
        "ssh_key":    None,
        "last_sync":  None,
        "last_commit":None,
        "sync_status":"never",
        "sync_error": None,
    }


def _save(data: dict) -> None:
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_CONFIG_FILE)
    except Exception as e:
        log.warning("gitops save fail: %s", e)


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list, cwd: Optional[str] = None, env: Optional[dict] = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run a git command."""
    try:
        r = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            cwd=cwd, env=env, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _kubectl(args: list, timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _build_git_env(ssh_key: Optional[str]) -> dict:
    """Build env dict with SSH key if provided."""
    env = os.environ.copy()
    if ssh_key:
        key_path = Path("/tmp/ankavm_gitops_key")
        try:
            key_path.write_text(ssh_key, encoding="utf-8")
            key_path.chmod(0o600)
            env["GIT_SSH_COMMAND"] = f"ssh -i {key_path} -o StrictHostKeyChecking=no"
        except Exception as e:
            log.warning("gitops ssh key write fail: %s", e)
    return env


def _get_current_commit(repo_dir: str) -> Optional[str]:
    rc, out, _ = _git(["rev-parse", "HEAD"], cwd=repo_dir)
    return out.strip() if rc == 0 else None


def _get_yaml_files(repo_dir: str, path: str) -> list:
    """Walk directory and return list of YAML file paths."""
    target = Path(repo_dir) / path
    if not target.exists():
        return []
    yaml_files = []
    for f in target.rglob("*.yaml"):
        yaml_files.append(str(f))
    for f in target.rglob("*.yml"):
        yaml_files.append(str(f))
    return sorted(yaml_files)


# ── Public API ────────────────────────────────────────────────────────────────

def configure_gitops(
    repo_url: str,
    branch: str = "main",
    path: str = ".",
    provider: str = "argocd",
    ssh_key: Optional[str] = None,
) -> dict:
    """Save GitOps configuration.

    Args:
        repo_url: Git repository HTTPS or SSH URL
        branch: Branch to track
        path: Path within repo containing manifests
        provider: 'argocd' or 'flux'
        ssh_key: Optional SSH private key content (PEM string)

    Returns:
        dict with ok, message
    """
    if provider not in _VALID_PROVIDERS:
        return {"ok": False, "error": f"provider must be one of {_VALID_PROVIDERS}"}
    if not repo_url:
        return {"ok": False, "error": "repo_url is required"}

    with _lock:
        data = _load()
        data.update({
            "configured": True,
            "repo_url":   repo_url,
            "branch":     branch,
            "path":       path,
            "provider":   provider,
            "ssh_key":    ssh_key,  # stored as-is; caller should manage key rotation
        })
        _save(data)

    log.info("gitops configured: url=%s branch=%s path=%s provider=%s", repo_url, branch, path, provider)
    return {"ok": True, "message": "GitOps configuration saved.", "provider": provider}


def get_config() -> dict:
    """Return current GitOps configuration (ssh_key masked)."""
    with _lock:
        data = _load()
    out = {k: v for k, v in data.items() if k != "ssh_key"}
    out["ssh_key_configured"] = bool(data.get("ssh_key"))
    return out


def sync_now() -> dict:
    """Pull latest commits, detect YAML diff, apply changed manifests.

    Returns:
        dict with ok, commit, files_changed, applied, errors
    """
    with _lock:
        data = _load()

    if not data.get("configured") or not data.get("repo_url"):
        return {"ok": False, "error": "GitOps not configured. Call configure_gitops first."}

    repo_url  = data["repo_url"]
    branch    = data.get("branch", "main")
    path      = data.get("path", ".")
    ssh_key   = data.get("ssh_key")
    repo_dir  = str(_SYNC_DIR)
    env       = _build_git_env(ssh_key)

    errors         = []
    files_changed  = []
    applied_files  = []

    # Clone or pull
    if not (_SYNC_DIR / ".git").exists():
        _SYNC_DIR.mkdir(parents=True, exist_ok=True)
        rc, _, stderr = _git(["clone", "--branch", branch, "--single-branch", repo_url, repo_dir], env=env)
        if rc != 0:
            msg = f"git clone failed: {stderr.strip()}"
            log.warning("gitops sync clone fail: %s", msg)
            with _lock:
                d2 = _load()
                d2["sync_status"] = "error"
                d2["sync_error"]  = msg
                d2["last_sync"]   = time.time()
                _save(d2)
            return {"ok": False, "error": msg}
    else:
        rc, _, stderr = _git(["fetch", "origin", branch], cwd=repo_dir, env=env)
        if rc != 0:
            errors.append(f"fetch error: {stderr.strip()}")
        # Capture diff before reset
        rc2, diff_out, _ = _git(
            ["diff", "--name-only", "HEAD", f"origin/{branch}"],
            cwd=repo_dir, env=env
        )
        if rc2 == 0:
            files_changed = [f for f in diff_out.splitlines() if f.endswith((".yaml", ".yml"))]
        rc3, _, stderr3 = _git(["reset", "--hard", f"origin/{branch}"], cwd=repo_dir, env=env)
        if rc3 != 0:
            errors.append(f"reset error: {stderr3.strip()}")

    commit = _get_current_commit(repo_dir)

    # Apply changed (or all) YAML files via kubectl
    yaml_files = files_changed if files_changed else _get_yaml_files(repo_dir, path)
    for yf in yaml_files:
        rc_a, _, stderr_a = _kubectl(["apply", "-f", yf])
        if rc_a == 0:
            applied_files.append(yf)
        else:
            errors.append(f"kubectl apply {yf}: {stderr_a.strip()}")

    ok = len(errors) == 0
    with _lock:
        d2 = _load()
        d2["last_sync"]   = time.time()
        d2["last_commit"] = commit
        d2["sync_status"] = "ok" if ok else "error"
        d2["sync_error"]  = "; ".join(errors) if errors else None
        _save(d2)

    log.info("gitops sync: ok=%s commit=%s changed=%d applied=%d errors=%d",
             ok, commit, len(files_changed), len(applied_files), len(errors))
    return {
        "ok":           ok,
        "commit":       commit,
        "files_changed":files_changed,
        "applied":      applied_files,
        "errors":       errors,
    }


def get_sync_status() -> dict:
    """Return last sync result and status summary."""
    with _lock:
        data = _load()

    current_commit = None
    if (_SYNC_DIR / ".git").exists():
        current_commit = _get_current_commit(str(_SYNC_DIR))

    return {
        "configured":    data.get("configured", False),
        "provider":      data.get("provider", "argocd"),
        "repo_url":      data.get("repo_url"),
        "branch":        data.get("branch", "main"),
        "path":          data.get("path", "."),
        "sync_status":   data.get("sync_status", "never"),
        "last_sync":     data.get("last_sync"),
        "last_commit":   data.get("last_commit"),
        "current_commit":current_commit,
        "sync_error":    data.get("sync_error"),
        "in_sync":       (data.get("last_commit") == current_commit
                          and data.get("sync_status") == "ok"),
    }


def generate_app_manifest() -> dict:
    """Generate ArgoCD Application or Flux GitRepository + Kustomization YAML.

    Returns:
        dict with provider, manifest_yaml, filename
    """
    with _lock:
        data = _load()

    provider = data.get("provider", "argocd")
    repo_url = data.get("repo_url", "https://github.com/example/ankavm-gitops")
    branch   = data.get("branch", "main")
    path     = data.get("path", ".")

    if provider == "argocd":
        manifest_yaml = f"""\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ankavm
  namespace: argocd
  labels:
    app.kubernetes.io/managed-by: ankavm
    ankavm.io/version: "2.5.10"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: {repo_url}
    targetRevision: {branch}
    path: {path}
  destination:
    server: https://kubernetes.default.svc
    namespace: ankavm-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  revisionHistoryLimit: 10
"""
        filename = "argocd-application.yaml"
    else:
        # Flux
        manifest_yaml = f"""\
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: ankavm
  namespace: flux-system
  labels:
    ankavm.io/version: "2.5.10"
spec:
  interval: 1m0s
  ref:
    branch: {branch}
  url: {repo_url}
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: ankavm
  namespace: flux-system
spec:
  interval: 5m0s
  path: "./{path}"
  prune: true
  sourceRef:
    kind: GitRepository
    name: ankavm
  targetNamespace: ankavm-system
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: ankavm-vm-operator
      namespace: ankavm-system
  timeout: 2m0s
  retryInterval: 30s
"""
        filename = "flux-gitops.yaml"

    log.info("gitops manifest generated: provider=%s", provider)
    return {
        "provider":      provider,
        "manifest_yaml": manifest_yaml,
        "filename":      filename,
        "repo_url":      repo_url,
        "branch":        branch,
    }






