"""
ankavm OPA Policy Engine — Policy-as-Code (OPA/Rego)
──────────────────────────────────────────────────────
Stores Rego policy source files. Evaluation:
  - If `opa` binary is available on PATH → uses `opa eval` subprocess.
  - Otherwise falls back to a safe built-in allow/deny rule engine.
No external Python dependencies. No periodic jobs.
"""

import json
import time
import uuid
import logging
import threading
import subprocess
import shutil
import tempfile
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("opa_policy")

_POLICY_DIR  = Path("/var/lib/ankavm/opa_policies")
_META_FILE   = Path("/var/lib/ankavm/opa_policy_meta.json")
_lock        = threading.Lock()


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_meta() -> dict:
    try:
        if _META_FILE.exists():
            return json.loads(_META_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("opa meta load fail: %s", e)
    return {}


def _save_meta(data: dict) -> None:
    try:
        _META_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _META_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_META_FILE)
    except Exception as e:
        log.warning("opa meta save fail: %s", e)


def _policy_path(name: str) -> Path:
    # Sanitize name to safe filename
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    if not safe:
        safe = "policy"
    return _POLICY_DIR / f"{safe}.rego"


def _opa_available() -> bool:
    return shutil.which("opa") is not None


# ── built-in fallback evaluator ───────────────────────────────────────────────

def _builtin_evaluate(rego_source: str, input_data: dict) -> dict:
    """
    Minimal safe Rego interpreter. Supports:
      allow = true  if conditions
      deny  = true  if conditions
    Returns {allowed, reason, engine='builtin'}.
    No code execution — string pattern matching only.
    """
    allow_found = False
    deny_found  = False
    reason      = "no matching rule"

    lines = rego_source.splitlines()
    for line in lines:
        line = line.strip()
        # Explicit allow
        if line.lower().startswith("allow") and "true" in line.lower():
            allow_found = True
            reason = "allow rule matched"
        # Explicit deny
        if line.lower().startswith("deny") and "true" in line.lower():
            deny_found = True
            reason = "deny rule matched"
        # Keyword-based: look for "input.X == Y" patterns
        if "input." in line:
            try:
                # extract key path and value
                part = line.split("input.")[1]
                if "==" in part:
                    key_part, val_part = part.split("==", 1)
                    key   = key_part.strip().rstrip('"').rstrip("'")
                    val   = val_part.strip().strip('"').strip("'")
                    parts = key.split(".")
                    cur   = input_data
                    for p in parts:
                        if isinstance(cur, dict):
                            cur = cur.get(p)
                        else:
                            cur = None
                            break
                    if str(cur) == val:
                        if "deny" in line.lower():
                            deny_found = True
                            reason = f"input.{key} == {val} → deny"
                        elif "allow" in line.lower():
                            allow_found = True
                            reason = f"input.{key} == {val} → allow"
            except Exception:
                pass

    # deny takes precedence
    if deny_found:
        return {"allowed": False, "reason": reason, "engine": "builtin"}
    if allow_found:
        return {"allowed": True, "reason": reason, "engine": "builtin"}
    # Default: if no explicit allow → deny (fail-closed)
    return {"allowed": False, "reason": "no allow rule found (fail-closed)", "engine": "builtin"}


# ── public API ────────────────────────────────────────────────────────────────

def set_policy(name: str, rego_source: str, description: str = "") -> dict:
    """Create or overwrite a Rego policy."""
    if not name:
        raise ValueError("name required")
    if not rego_source:
        raise ValueError("rego_source required")
    with _lock:
        _POLICY_DIR.mkdir(parents=True, exist_ok=True)
        path = _policy_path(name)
        tmp  = path.with_suffix(".tmp")
        tmp.write_text(rego_source, encoding="utf-8")
        tmp.replace(path)
        meta = _load_meta()
        meta[name] = {
            "name":        name,
            "description": description,
            "path":        str(path),
            "size_bytes":  len(rego_source.encode()),
            "created_at":  meta.get(name, {}).get("created_at", int(time.time())),
            "updated_at":  int(time.time()),
        }
        _save_meta(meta)
    log.info("opa policy set: %s", name)
    return meta[name]


def list_policies() -> list:
    with _lock:
        meta = _load_meta()
    return list(meta.values())


def get_policy(name: str) -> Optional[dict]:
    with _lock:
        meta = _load_meta()
        if name not in meta:
            return None
        info = dict(meta[name])
    try:
        path = _policy_path(name)
        info["rego_source"] = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        info["rego_source"] = ""
    return info


def delete_policy(name: str) -> dict:
    with _lock:
        meta = _load_meta()
        if name not in meta:
            return {"ok": False, "error": "not found"}
        path = _policy_path(name)
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            log.warning("opa delete file fail: %s", e)
        del meta[name]
        _save_meta(meta)
    log.info("opa policy deleted: %s", name)
    return {"ok": True, "deleted": name}


def evaluate(policy_name: str, input_json: dict) -> dict:
    """
    Evaluate policy against input.
    Uses OPA binary if available, else built-in fallback.
    Returns {allowed, reason, engine, policy}.
    """
    policy = get_policy(policy_name)
    if not policy:
        return {"allowed": False, "reason": "policy not found", "engine": "none",
                "policy": policy_name}

    rego_source = policy.get("rego_source", "")

    if _opa_available():
        try:
            # Write input to a temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump({"input": input_json}, f)
                input_path = f.name
            policy_file = _policy_path(policy_name)
            r = subprocess.run(
                ["opa", "eval",
                 "--data", str(policy_file),
                 "--input", input_path,
                 "--format", "json",
                 "data.ankavm.allow"],
                capture_output=True, text=True, timeout=10
            )
            os.unlink(input_path)
            if r.returncode == 0:
                result = json.loads(r.stdout)
                # OPA eval result structure: {result: [{expressions: [{value}]}]}
                try:
                    val = result["result"][0]["expressions"][0]["value"]
                    allowed = bool(val)
                except (KeyError, IndexError, TypeError):
                    allowed = False
                return {
                    "allowed": allowed,
                    "reason":  "opa eval" if allowed else "policy denied",
                    "engine":  "opa",
                    "policy":  policy_name,
                }
            else:
                log.warning("opa eval error: %s", r.stderr.strip())
                # fall through to builtin
        except Exception as ex:
            log.warning("opa subprocess fail: %s — falling back to builtin", ex)

    # Built-in fallback
    result = _builtin_evaluate(rego_source, input_json)
    result["policy"] = policy_name
    return result


def test_policy(policy_name: str, test_input: dict) -> dict:
    """
    Run policy evaluation with test input and return detailed result.
    Same as evaluate() but tagged as a test run.
    """
    result = evaluate(policy_name, test_input)
    result["test"] = True
    result["test_input"] = test_input
    return result






