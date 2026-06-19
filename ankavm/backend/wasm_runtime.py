"""
wasm_runtime.py â€” WebAssembly Runtime Manager for ankavm
ankavm v2.5.11 Modern Workloads

Features:
  - detect_wasm() â€” wasmtime/wasmedge/wasmer binary {available, runtime, version}
  - run_wasm_module(wasm_path, args, env) â€” run a .wasm module via detected runtime
  - list_wasm_modules() â€” list registered .wasm modules
  - register_module(name, path, description) â€” register a .wasm module in the registry

Config persisted to /var/lib/ankavm/wasm_modules.json
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

log = logging.getLogger("wasm_runtime")

_DATA_FILE = Path("/var/lib/ankavm/wasm_modules.json")
_lock = threading.Lock()

_WASM_RUNTIMES = [
    ("wasmtime",  "/usr/bin/wasmtime"),
    ("wasmtime",  "/usr/local/bin/wasmtime"),
    ("wasmtime",  "wasmtime"),
    ("wasmedge",  "/usr/bin/wasmedge"),
    ("wasmedge",  "/usr/local/bin/wasmedge"),
    ("wasmedge",  "wasmedge"),
    ("wasmer",    "/usr/bin/wasmer"),
    ("wasmer",    "/usr/local/bin/wasmer"),
    ("wasmer",    "wasmer"),
]

_WASM_RUN_TIMEOUT = 30  # seconds default timeout for wasm execution


# â”€â”€ Persistent store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load() -> dict:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("wasm load fail: %s", e)
    return {"modules": {}}


def _save(data: dict) -> None:
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_DATA_FILE)
    except Exception as e:
        log.warning("wasm save fail: %s", e)


# â”€â”€ Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def detect_wasm() -> dict:
    """Detect available WASM runtime. Returns first found (wasmtime > wasmedge > wasmer)."""
    result = {
        "available": False,
        "runtime":   None,
        "binary":    None,
        "version":   None,
        "all_found": [],
        "error":     None,
    }
    found_all = []
    for runtime_name, candidate in _WASM_RUNTIMES:
        try:
            if "/" in candidate:
                if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
                    continue
                binary = candidate
            else:
                r = subprocess.run(["which", candidate], capture_output=True, text=True, timeout=5)
                if r.returncode != 0:
                    continue
                binary = r.stdout.strip()
            if binary and binary not in [f["binary"] for f in found_all]:
                found_all.append({"runtime": runtime_name, "binary": binary})
        except Exception:
            continue
    if not found_all:
        result["error"] = "no WASM runtime found (wasmtime/wasmedge/wasmer)"
        return result
    # Primary: first found
    primary = found_all[0]
    result["runtime"] = primary["runtime"]
    result["binary"]  = primary["binary"]
    result["all_found"] = [f["runtime"] for f in found_all]
    # Get version
    try:
        r = subprocess.run([primary["binary"], "--version"], capture_output=True, text=True, timeout=5)
        line = (r.stdout or r.stderr or "").strip().splitlines()
        result["version"] = line[0] if line else "unknown"
    except Exception as e:
        result["version"] = "unknown"
        log.debug("wasm version error: %s", e)
    result["available"] = True
    return result


# â”€â”€ Module registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def list_wasm_modules() -> list:
    """Return list of registered WASM modules."""
    with _lock:
        data = _load()
    modules = list(data.get("modules", {}).values())
    # Annotate with file existence
    for m in modules:
        m["file_exists"] = os.path.isfile(m.get("path", ""))
    return modules


def register_module(name: str, path: str, description: str = "") -> dict:
    """Register a .wasm module in the registry."""
    if not name or not path:
        return {"registered": False, "error": "name and path required"}
    module_id = name.lower().replace(" ", "_").replace("-", "_")
    record = {
        "id":          module_id,
        "name":        name,
        "path":        path,
        "description": description,
        "registered_at": int(time.time()),
    }
    with _lock:
        data = _load()
        data["modules"][module_id] = record
        _save(data)
    return {"registered": True, "module": record}


# â”€â”€ Execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_wasm_module(
    wasm_path: str,
    args: Optional[list] = None,
    env: Optional[dict] = None,
    timeout: int = _WASM_RUN_TIMEOUT,
) -> dict:
    """
    Run a .wasm module using the detected WASM runtime (default: wasmtime).
    Returns stdout, stderr, returncode, elapsed_ms.
    """
    if not wasm_path:
        return {"success": False, "error": "wasm_path required"}
    if not os.path.isfile(wasm_path):
        return {"success": False, "error": f"file not found: {wasm_path}"}

    det = detect_wasm()
    if not det.get("available"):
        return {"success": False, "error": det.get("error", "no wasm runtime")}

    binary  = det["binary"]
    runtime = det["runtime"]
    cmd     = [binary, wasm_path]
    if args:
        cmd += [str(a) for a in args]

    run_env = os.environ.copy()
    if env:
        run_env.update({str(k): str(v) for k, v in env.items()})

    t0 = time.time()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "success":     r.returncode == 0,
            "returncode":  r.returncode,
            "stdout":      r.stdout[:65536],
            "stderr":      r.stderr[:8192],
            "elapsed_ms":  elapsed_ms,
            "runtime":     runtime,
            "wasm_path":   wasm_path,
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {
            "success":    False,
            "error":      f"timeout after {timeout}s",
            "elapsed_ms": elapsed_ms,
            "runtime":    runtime,
            "wasm_path":  wasm_path,
        }
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        log.warning("run_wasm_module fail: %s", e)
        return {"success": False, "error": str(e), "elapsed_ms": elapsed_ms}






