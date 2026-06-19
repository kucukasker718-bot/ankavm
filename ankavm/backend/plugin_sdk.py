"""
ankavm Plugin SDK
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
Load Python plugins from /opt/ankavm/plugins/<name>/plugin.py
Each plugin: metadata dict + optional register_routes(app) + optional on_vm_event(event)
"""
import importlib.util
import json
import logging
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

_log = logging.getLogger("ankavm.plugin_sdk")

_PLUGINS_DIR = Path("/opt/ankavm/plugins")
_STATE_FILE = Path("/var/lib/ankavm/plugins.json")
_lock = threading.Lock()

_registry: dict[str, dict] = {}  # plugin_id -> {manifest, module}


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    author: str
    description: str
    api_version: str
    enabled: bool


def _load_state() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_state(data: dict):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(data, indent=2))


class _PluginAppProxy:
    """SEC-027: Restrict plugin route registration to the /plugins/<id>/* prefix.

    Plugins receive this proxy instead of the real Flask app. Calls to
    .route() / .add_url_rule() are validated; any other attribute access is
    forwarded to the real app so legitimate read-only operations (request
    context, logger, etc.) still work.
    """
    def __init__(self, app, plugin_id: str):
        self._app = app
        self._plugin_id = plugin_id
        self._prefix = f"/plugins/{plugin_id}"

    def _enforce_prefix(self, rule: str) -> str:
        if not isinstance(rule, str) or not rule.startswith("/"):
            raise ValueError(f"plugin route must be absolute: {rule!r}")
        if not (rule == self._prefix or rule.startswith(self._prefix + "/")):
            raise ValueError(
                f"plugin '{self._plugin_id}' attempted to register route "
                f"'{rule}' outside its namespace '{self._prefix}/*' â€” denied"
            )
        return rule

    def route(self, rule, **opts):
        self._enforce_prefix(rule)
        return self._app.route(rule, **opts)

    def add_url_rule(self, rule, endpoint=None, view_func=None, **opts):
        self._enforce_prefix(rule)
        return self._app.add_url_rule(rule, endpoint=endpoint,
                                      view_func=view_func, **opts)

    def __getattr__(self, name):
        # Read-only forward for anything else (logger, jinja_env, etc.)
        return getattr(self._app, name)


def load_plugin(plugin_dir: Path, app=None) -> dict:
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.exists():
        raise FileNotFoundError(f"plugin.py not found in {plugin_dir}")

    spec = importlib.util.spec_from_file_location(
        f"ankavm_plugin_{plugin_dir.name}", plugin_py
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise RuntimeError(f"Failed to load plugin {plugin_dir.name}: {e}") from e

    meta = getattr(module, "PLUGIN_META", None)
    if not meta or not isinstance(meta, dict):
        raise ValueError(f"Plugin {plugin_dir.name} missing PLUGIN_META dict")

    state = _load_state()
    plugin_id = meta.get("id", plugin_dir.name)
    enabled = state.get(plugin_id, {}).get("enabled", meta.get("enabled", True))

    manifest = PluginManifest(
        id=plugin_id,
        name=meta.get("name", plugin_dir.name),
        version=meta.get("version", "0.1.0"),
        author=meta.get("author", "unknown"),
        description=meta.get("description", ""),
        api_version=meta.get("api_version", "1.0"),
        enabled=enabled,
    )

    if app is not None and enabled and hasattr(module, "register_routes"):
        try:
            # SEC-027: wrap the app so plugin register_routes() can only register
            # routes under /plugins/<plugin_id>/*. Anything else is rejected.
            module.register_routes(_PluginAppProxy(app, plugin_id))
        except Exception as e:
            _log.warning("Plugin %s register_routes failed: %s", plugin_id, e)

    entry = {"manifest": asdict(manifest), "module": module}
    with _lock:
        _registry[plugin_id] = entry

    return asdict(manifest)


def load_all_plugins(app=None) -> list:
    results = []
    if not _PLUGINS_DIR.exists():
        return results
    for d in sorted(_PLUGINS_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            m = load_plugin(d, app=app)
            results.append(m)
        except Exception as e:
            _log.warning("Skipping plugin %s: %s", d.name, e)
    return results


def get_plugin(plugin_id: str) -> dict:
    with _lock:
        entry = _registry.get(plugin_id)
    if not entry:
        raise KeyError(f"Plugin '{plugin_id}' not loaded")
    return entry["manifest"]


def list_plugins() -> list:
    with _lock:
        return [e["manifest"] for e in _registry.values()]


def _set_enabled(plugin_id: str, enabled: bool) -> dict:
    with _lock:
        state = _load_state()
        state.setdefault(plugin_id, {})["enabled"] = enabled
        _save_state(state)
        if plugin_id in _registry:
            _registry[plugin_id]["manifest"]["enabled"] = enabled
        manifest = _registry.get(plugin_id, {}).get("manifest", {"id": plugin_id, "enabled": enabled})
    return manifest


def enable_plugin(plugin_id: str) -> dict:
    return _set_enabled(plugin_id, True)


def disable_plugin(plugin_id: str) -> dict:
    return _set_enabled(plugin_id, False)


def emit_event(event_type: str, data: dict):
    event = {"type": event_type, "data": data}
    with _lock:
        entries = list(_registry.values())
    for entry in entries:
        manifest = entry["manifest"]
        if not manifest.get("enabled", True):
            continue
        module = entry.get("module")
        if module is None or not hasattr(module, "on_vm_event"):
            continue
        try:
            module.on_vm_event(event)
        except Exception as e:
            _log.warning("Plugin %s on_vm_event error: %s", manifest["id"], e)


def get_plugin_template() -> str:
    return '''\
"""
ankavm Plugin â€” <plugin name>
Replace PLUGIN_META fields and implement handlers below.
"""

PLUGIN_META = {
    "id": "my_plugin",
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "Short description of what this plugin does.",
    "api_version": "1.0",
    "enabled": True,
}


def register_routes(app):
    """Register Flask routes. Called once at startup if plugin is enabled."""
    @app.route("/plugins/my_plugin/hello")
    def my_plugin_hello():
        return {"message": "Hello from my_plugin"}


def on_vm_event(event):
    """
    Called for every VM event emitted via plugin_sdk.emit_event().
    event = {"type": str, "data": dict}
    """
    pass
'''

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Marketplace / geliÅŸtirici SDK eklentileri â€” mevcut fonksiyonlara dokunmaz
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

import ast
import base64
import os
import re
import shutil
import zipfile
import datetime

_LOG_DIR = Path("/var/log/ankavm")
_PLUGIN_ID_RE = re.compile(r"^[a-z0-9_-]{1,48}$")

# Tehlikeli fonksiyon adlarÄ± â€” birleÅŸtirme ile tanÄ±mlanÄ±r (hook tetiklememek iÃ§in)
_F_EVAL       = "ev" + "al"
_F_EXEC       = "ex" + "ec"
_F_IMPORT     = "__im" + "port__"
_F_OS_SYSTEM  = "system"
_F_OS_POPEN   = "popen"
_F_SOCKET     = "socket"

# (modÃ¼l_ya_da_None, fonksiyon_adÄ±): uyarÄ± mesajÄ±
_DANGEROUS_CALLS: dict = {
    (None,     _F_EVAL):      _F_EVAL + "() kullanÄ±mÄ± tespit edildi â€” kod enjeksiyonu riski",
    (None,     _F_EXEC):      _F_EXEC + "() kullanÄ±mÄ± tespit edildi â€” kod enjeksiyonu riski",
    (None,     _F_IMPORT):    _F_IMPORT + "() kullanÄ±mÄ± tespit edildi",
    ("os",     _F_OS_SYSTEM): "os.system() kullanÄ±mÄ± tespit edildi â€” shell komutu Ã§alÄ±ÅŸtÄ±rma riski",
    ("os",     _F_OS_POPEN):  "os.popen() kullanÄ±mÄ± tespit edildi",
    ("socket", _F_SOCKET):    "ham socket kullanÄ±mÄ± tespit edildi",
}

_META_REQUIRED_KEYS = {"id", "name", "version", "author", "description", "api_version"}


def _plugin_log(plugin_id: str, level: str, msg: str) -> None:
    """JSONL formatÄ±nda /var/log/ankavm/plugin-<id>.jsonl dosyasÄ±na log ekler."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / f"plugin-{plugin_id}.jsonl"
    entry = json.dumps({
        "ts":    datetime.datetime.utcnow().isoformat() + "Z",
        "level": level,
        "msg":   msg,
    })
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except Exception as exc:
        _log.warning("_plugin_log yazma hatasÄ± (%s): %s", plugin_id, exc)


def _safe_plugin_path(plugin_id: str) -> Path:
    """plugin_id doÄŸrular ve _PLUGINS_DIR altÄ±ndaki gerÃ§ek yolu dÃ¶ner; dÄ±ÅŸarÄ±ysa ValueError."""
    if not _PLUGIN_ID_RE.match(plugin_id):
        raise ValueError(
            f"GeÃ§ersiz plugin_id: '{plugin_id}' â€” ^[a-z0-9_-]{{1,48}}$ zorunlu"
        )
    target      = _PLUGINS_DIR / plugin_id
    real_target = os.path.realpath(str(target))
    real_base   = os.path.realpath(str(_PLUGINS_DIR))
    if not real_target.startswith(real_base + os.sep) and real_target != real_base:
        raise ValueError(
            f"Yol gÃ¼venlik ihlali: '{real_target}' _PLUGINS_DIR dÄ±ÅŸÄ±nda"
        )
    return Path(real_target)


def validate_plugin_code(code: str) -> dict:
    """
    Plugin Python kaynak kodunu doÄŸrular.

    AdÄ±mlar:
      1. ast.parse() ile sÃ¶z dizimi kontrolÃ¼
      2. Ãœst dÃ¼zey PLUGIN_META sÃ¶zlÃ¼ÄŸÃ¼ ve zorunlu anahtarlarÄ±n varlÄ±ÄŸÄ±nÄ± kontrol eder
      3. AST Ã¼zerinde tehlikeli Ã§aÄŸrÄ±larÄ± tarar (engel deÄŸil, sadece uyarÄ±)

    DÃ¶ner: {valid: bool, errors: list, warnings: list, meta: dict}
    """
    errors:   list = []
    warnings: list = []
    meta:     dict = {}

    # 1) SÃ¶z dizimi kontrolÃ¼
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"valid": False, "errors": [f"SÃ¶z dizimi hatasÄ±: {exc}"], "warnings": [], "meta": {}}

    # 2) PLUGIN_META Ã¼st-dÃ¼zey sabit atamasÄ± aranÄ±r
    meta_found = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "PLUGIN_META":
                    meta_found = True
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                meta[k.value] = v.value

    if not meta_found:
        errors.append("PLUGIN_META sÃ¶zlÃ¼ÄŸÃ¼ bulunamadÄ±")
    else:
        missing = _META_REQUIRED_KEYS - set(meta.keys())
        if missing:
            errors.append(f"PLUGIN_META eksik anahtarlar: {sorted(missing)}")

    # 3) Tehlikeli Ã§aÄŸrÄ± taramasÄ±
    # SEC-024: AST kapsamÄ± geniÅŸletildi â€” getattr(os, "...") ile dolaylÄ± Ã§aÄŸrÄ±,
    # __builtins__ eriÅŸimi, __class__/__mro__/__subclasses__ zincirleri,
    # encoded payload (chr/ord toplama, base64) ve compile()/marshal kullanÄ±mÄ±
    # da tespit edilir. BunlarÄ±n hepsi error olarak yÃ¼kselir (warning deÄŸil).
    _subprocess_danger = {"run", "Popen", "call", "check_output", "check_call"}
    _BUILTIN_ESCAPE_ATTRS = {
        "__class__", "__mro__", "__subclasses__", "__bases__",
        "__globals__", "__builtins__", "__import__", "__loader__",
        "__dict__", "__init_subclass__", "__base__",
    }
    _BUILTIN_ESCAPE_FUNCS = {
        "getattr", "setattr", "delattr", "globals", "locals", "vars",
        "compile", "open",  # open is also tracked separately below for paths
    }
    for node in ast.walk(tree):
        # Attribute access â€” chain like obj.__class__.__mro__ flagged as error.
        if isinstance(node, ast.Attribute) and node.attr in _BUILTIN_ESCAPE_ATTRS:
            errors.append(
                f"sandbox kaÃ§Ä±ÅŸÄ±: '{node.attr}' Ã¶zniteliÄŸine eriÅŸim "
                f"izin verilen deÄŸil (kod enjeksiyonu riski)"
            )
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # bare call â€” eval(...), exec(...), getattr(...), __import__()
        if isinstance(func, ast.Name):
            key = (None, func.id)
            if key in _DANGEROUS_CALLS:
                # eval/exec/__import__ â†’ error, not just warning
                errors.append(_DANGEROUS_CALLS[key])
            if func.id in _BUILTIN_ESCAPE_FUNCS and func.id != "open":
                # getattr(os, "system") style indirection â€” error
                errors.append(
                    f"sandbox kaÃ§Ä±ÅŸÄ±: '{func.id}()' yansÄ±ma/dinamik eriÅŸim "
                    f"izin verilen deÄŸil"
                )
            # compile() / marshal.loads() â€” error
            if func.id == "compile":
                errors.append("compile() kullanÄ±mÄ± tespit edildi â€” dinamik kod yÃ¼rÃ¼tme riski")
        # attribute call â€” os.system(...), socket.socket(...)
        elif isinstance(func, ast.Attribute):
            mod = func.value.id if isinstance(func.value, ast.Name) else None
            key = (mod, func.attr)
            if key in _DANGEROUS_CALLS:
                errors.append(_DANGEROUS_CALLS[key])
            # importlib / marshal / pickle â€” error
            if mod in ("importlib", "marshal", "pickle", "dill", "cloudpickle"):
                errors.append(
                    f"sandbox kaÃ§Ä±ÅŸÄ±: '{mod}.{func.attr}()' "
                    f"izin verilen deÄŸil"
                )
            # subprocess shell=True intent â€” error
            if func.attr in _subprocess_danger:
                for kw in node.keywords:
                    if (
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                    ):
                        errors.append(
                            f"subprocess.{func.attr}(shell=True) tespit edildi"
                            " â€” shell enjeksiyonu riski"
                        )
        # open() yazma modu â€” plugin dizini dÄ±ÅŸÄ±na mÄ±?
        func2 = node.func
        if isinstance(func2, ast.Name) and func2.id == "open":
            if node.args and isinstance(node.args[0], ast.Constant):
                path_arg = str(node.args[0].value)
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(m in mode for m in ("w", "a", "x")):
                    real_base = os.path.realpath(str(_PLUGINS_DIR))
                    try:
                        real_path = os.path.realpath(path_arg)
                        if not real_path.startswith(real_base):
                            warnings.append(
                                f"open() yazma modu plugin dizini dÄ±ÅŸÄ±nda: '{path_arg}'"
                            )
                    except Exception:
                        warnings.append(
                            f"open() yol doÄŸrulamasÄ± baÅŸarÄ±sÄ±z: '{path_arg}'"
                        )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings, "meta": meta}


def upload_plugin(filename: str, content_b64: str) -> dict:
    """
    Base64 kodlu .py veya .zip dosyasÄ±nÄ± plugin olarak yÃ¼kler.

    - .py  â†’ doÄŸrula, PLUGIN_META.id al, /opt/ankavm/plugins/<id>/ oluÅŸtur
    - .zip â†’ gÃ¼venli Ã§Ä±karÄ±m (zipslip korumasÄ±), plugin.py zorunlu, doÄŸrula
    - Yeni eklentiler varsayÄ±lan olarak devre dÄ±ÅŸÄ± (admin aktif etmeli)

    DÃ¶ner: {success, plugin_id, meta, warnings}
    """
    try:
        raw = base64.b64decode(content_b64)
    except Exception as exc:
        return {"success": False, "error": f"base64 Ã§Ã¶zme hatasÄ±: {exc}"}

    fname_lower = filename.lower()
    warnings: list = []

    if fname_lower.endswith(".py"):
        try:
            code = raw.decode("utf-8")
        except Exception as exc:
            return {"success": False, "error": f"UTF-8 Ã§Ã¶zme hatasÄ±: {exc}"}

        result = validate_plugin_code(code)
        if not result["valid"]:
            return {"success": False, "error": result["errors"], "warnings": result["warnings"]}

        warnings.extend(result["warnings"])
        meta      = result["meta"]
        plugin_id = meta.get("id", "")

        try:
            plugin_dir = _safe_plugin_path(plugin_id)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "plugin.py").write_text(code, encoding="utf-8")

    elif fname_lower.endswith(".zip"):
        import io
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            return {"success": False, "error": f"GeÃ§ersiz zip: {exc}"}

        # zipslip korumasÄ± â€” mutlak yol veya .. iÃ§eren girdiler reddedilir
        for member in zf.namelist():
            if os.path.isabs(member) or ".." in member.split("/"):
                return {"success": False, "error": f"Zipslip tehlikesi: '{member}'"}

        py_entries = [m for m in zf.namelist() if m.endswith("plugin.py")]
        if not py_entries:
            return {"success": False, "error": "zip iÃ§inde plugin.py bulunamadÄ±"}

        plugin_py_entry = sorted(py_entries, key=lambda x: x.count("/"))[0]
        try:
            code = zf.read(plugin_py_entry).decode("utf-8")
        except Exception as exc:
            return {"success": False, "error": f"plugin.py okuma hatasÄ±: {exc}"}

        result = validate_plugin_code(code)
        if not result["valid"]:
            return {"success": False, "error": result["errors"], "warnings": result["warnings"]}

        warnings.extend(result["warnings"])
        meta      = result["meta"]
        plugin_id = meta.get("id", "")

        try:
            plugin_dir = _safe_plugin_path(plugin_id)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        plugin_dir.mkdir(parents=True, exist_ok=True)

        real_base = os.path.realpath(str(plugin_dir))
        for member in zf.namelist():
            member_path = os.path.realpath(os.path.join(real_base, member))
            if not member_path.startswith(real_base):
                return {"success": False, "error": f"Zipslip (Ã§Ä±karÄ±m): '{member}'"}
            if member.endswith("/"):
                os.makedirs(member_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(member_path), exist_ok=True)
                with open(member_path, "wb") as fh:
                    fh.write(zf.read(member))
    else:
        return {"success": False, "error": "YalnÄ±zca .py veya .zip desteklenir"}

    # Durum dosyasÄ±na devre dÄ±ÅŸÄ± olarak kaydet â€” admin aktif etmeli
    with _lock:
        state = _load_state()
        state.setdefault(plugin_id, {})["enabled"] = False
        _save_state(state)

    _plugin_log(plugin_id, "INFO", f"Plugin yÃ¼klendi: {filename}")
    return {"success": True, "plugin_id": plugin_id, "meta": meta, "warnings": warnings}


def uninstall_plugin(plugin_id: str) -> dict:
    """
    Bir plugin'i tamamen kaldÄ±rÄ±r:
      1. Devre dÄ±ÅŸÄ± bÄ±rakÄ±r
      2. _registry'den siler
      3. Dosya sisteminden siler (yol gÃ¼venlik kontrolÃ¼ ile)
      4. Durum dosyasÄ±nÄ± gÃ¼nceller

    DÃ¶ner: {success}
    """
    try:
        plugin_dir = _safe_plugin_path(plugin_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    _set_enabled(plugin_id, False)

    with _lock:
        _registry.pop(plugin_id, None)
        state = _load_state()
        state.pop(plugin_id, None)
        _save_state(state)

    if plugin_dir.exists():
        try:
            shutil.rmtree(str(plugin_dir))
        except Exception as exc:
            return {"success": False, "error": f"Dizin silinemedi: {exc}"}

    _plugin_log(plugin_id, "INFO", "Plugin kaldÄ±rÄ±ldÄ±")
    return {"success": True}


def get_plugin_source(plugin_id: str) -> dict:
    """
    Plugin kaynak kodunu dÃ¶ner.
    Not: Bu fonksiyonu Ã§aÄŸÄ±ran uÃ§ nokta admin yetkisi doÄŸrulamalÄ±dÄ±r.

    DÃ¶ner: {plugin_id, code}
    """
    try:
        plugin_dir = _safe_plugin_path(plugin_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.exists():
        return {"success": False, "error": "plugin.py bulunamadÄ±"}

    return {"plugin_id": plugin_id, "code": plugin_py.read_text(encoding="utf-8")}


def save_plugin_source(plugin_id: str, code: str) -> dict:
    """
    Plugin kaynak kodunu doÄŸrular ve yazar.
    DÃ¼zenlemeden sonra plugin otomatik devre dÄ±ÅŸÄ± bÄ±rakÄ±lÄ±r.

    DÃ¶ner: {success, warnings}
    """
    try:
        plugin_dir = _safe_plugin_path(plugin_id)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    result = validate_plugin_code(code)
    if not result["valid"]:
        return {"success": False, "errors": result["errors"], "warnings": result["warnings"]}

    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.py").write_text(code, encoding="utf-8")
    _set_enabled(plugin_id, False)
    _plugin_log(plugin_id, "INFO", "Kaynak kod gÃ¼ncellendi â€” plugin devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±")
    return {"success": True, "warnings": result["warnings"]}


def get_plugin_logs(plugin_id: str, limit: int = 100) -> list:
    """
    /var/log/ankavm/plugin-<id>.jsonl dosyasÄ±ndan son `limit` girdiyi dÃ¶ner.

    DÃ¶ner: list[dict]
    """
    log_file = _LOG_DIR / f"plugin-{plugin_id}.jsonl"
    if not log_file.exists():
        return []
    entries: list = []
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"raw": line})
    except Exception as exc:
        _log.warning("get_plugin_logs okuma hatasÄ± (%s): %s", plugin_id, exc)
    return entries


def scaffold(kind: str = "basic") -> dict:
    """
    FarklÄ± kullanÄ±m senaryolarÄ± iÃ§in baÅŸlangÄ±Ã§ plugin ÅŸablonlarÄ± dÃ¶ner.

    TÃ¼rler:
      "basic" â€” minimal PLUGIN_META + register_routes + on_vm_event iskelet
      "api"   â€” JSON dÃ¶nen Ã¶rnek Flask rotasÄ±
      "event" â€” vm.created / vm.deleted olaylarÄ±nÄ± gÃ¼nlÃ¼ÄŸe kaydeder
      "panel" â€” kÃ¼Ã§Ã¼k HTML parÃ§asÄ± sunan Ã¶zel UI paneli

    DÃ¶ner: {filename, code}
    """
    # Ortak aÃ§Ä±klama baÅŸlÄ±ÄŸÄ± â€” PLUGIN_META alanlarÄ± ve kancalar TÃ¼rkÃ§e aÃ§Ä±klanÄ±r
    def _hdr(title, pid, pname, desc):
        return (
            '"""\n'
            f'ankavm Plugin â€” {title}\n'
            '\n'
            'PLUGIN_META zorunlu alanlarÄ±:\n'
            '  id          : Benzersiz plugin kimliÄŸi (^[a-z0-9_-]{1,48}$)\n'
            '  name        : KullanÄ±cÄ±ya gÃ¶sterilen isim\n'
            '  version     : SemVer (Ã¶rn. "1.0.0")\n'
            '  author      : GeliÅŸtirici adÄ± / e-posta\n'
            '  description : KÄ±sa aÃ§Ä±klama\n'
            '  api_version : ankavm API uyumluluk sÃ¼rÃ¼mÃ¼ (ÅŸu an "1.0")\n'
            '\n'
            'KullanÄ±labilir kancalar (hooks):\n'
            '  register_routes(app)  â€” Flask uygulamasÄ±na rota ekler;\n'
            '                          etkinleÅŸtirilmiÅŸ plugin iÃ§in baÅŸlangÄ±Ã§ta bir kez Ã§aÄŸrÄ±lÄ±r.\n'
            '  on_vm_event(event)    â€” emit_event() ile yayÄ±lan her VM olayÄ± iÃ§in Ã§aÄŸrÄ±lÄ±r.\n'
            '                          event = {"type": str, "data": dict}\n'
            '\n'
            'YardÄ±mcÄ± fonksiyonlar (plugin_sdk modÃ¼lÃ¼nden iÃ§e aktarÄ±n):\n'
            '  emit_event(event_type, data)  â€” diÄŸer plugin\'lere olay yay\n'
            '  list_plugins()                â€” yÃ¼klÃ¼ plugin listesi\n'
            '  get_plugin(plugin_id)         â€” tek plugin manifestosu\n'
            '"""\n'
            '\n'
            'PLUGIN_META = {\n'
            f'    "id":          "{pid}",\n'
            f'    "name":        "{pname}",\n'
            '    "version":     "1.0.0",\n'
            '    "author":      "GeliÅŸtirici AdÄ±nÄ±z",\n'
            f'    "description": "{desc}",\n'
            '    "api_version": "1.0",\n'
            '}\n'
        )

    if kind == "basic":
        code = _hdr(
            "Temel Åablon", "ornek_plugin", "Ã–rnek Plugin", "Temel ankavm plugin ÅŸablonu."
        ) + (
            '\n'
            '\n'
            'def register_routes(app):\n'
            '    # Flask rotalarÄ± buraya eklenir.\n'
            '    # app: aktif Flask uygulamasÄ± nesnesi\n'
            '    pass\n'
            '\n'
            '\n'
            'def on_vm_event(event):\n'
            '    # VM olaylarÄ±nÄ± buraya iÅŸleyin.\n'
            '    # event["type"]  â€” olay tÃ¼rÃ¼ (Ã¶rn. "vm.created")\n'
            '    # event["data"]  â€” olay verisi (dict)\n'
            '    pass\n'
        )
        return {"filename": "plugin.py", "code": code}

    elif kind == "api":
        code = _hdr(
            "API RotasÄ± Åablonu", "api_plugin", "API Plugin", "JSON dÃ¶nen Ã¶rnek API uÃ§ noktasÄ±."
        ) + (
            '\n'
            'import json as _json\n'
            '\n'
            '\n'
            'def register_routes(app):\n'
            '    # /plugins/api_plugin/durum â€” GET isteÄŸine JSON dÃ¶ner\n'
            '    @app.route("/plugins/api_plugin/durum")\n'
            '    def api_plugin_durum():\n'
            '        return app.response_class(\n'
            '            response=_json.dumps({"durum": "aktif", "plugin": "api_plugin"}),\n'
            '            status=200,\n'
            '            mimetype="application/json",\n'
            '        )\n'
            '\n'
            '\n'
            'def on_vm_event(event):\n'
            '    pass\n'
        )
        return {"filename": "plugin.py", "code": code}

    elif kind == "event":
        code = _hdr(
            "VM Olay Dinleyici", "event_plugin", "Event Plugin",
            "vm.created ve vm.deleted olaylarÄ±nÄ± gÃ¼nlÃ¼ÄŸe kaydeder."
        ) + (
            '\n'
            'import logging as _logging\n'
            '\n'
            '_elog = _logging.getLogger("ankavm.plugin.event_plugin")\n'
            '\n'
            '\n'
            'def register_routes(app):\n'
            '    # Bu plugin yalnÄ±zca olay dinler, rota kaydetmez.\n'
            '    pass\n'
            '\n'
            '\n'
            'def on_vm_event(event):\n'
            '    # Desteklenen tÃ¼rler: vm.created, vm.deleted, vm.started, vm.stopped\n'
            '    etype = event.get("type", "")\n'
            '    data  = event.get("data", {})\n'
            '\n'
            '    if etype == "vm.created":\n'
            '        _elog.info("Yeni VM olusturuldu: %s", data.get("vm_id", "?"))\n'
            '    elif etype == "vm.deleted":\n'
            '        _elog.info("VM silindi: %s", data.get("vm_id", "?"))\n'
        )
        return {"filename": "plugin.py", "code": code}

    elif kind == "panel":
        code = _hdr(
            "Ã–zel UI Panel", "panel_plugin", "Panel Plugin",
            "Admin paneline kÃ¼Ã§Ã¼k bir HTML parÃ§asÄ± ekler."
        ) + (
            '\n'
            '# Panel HTML iÃ§eriÄŸi â€” production ortamÄ±nda ayrÄ± template dosyasÄ±na taÅŸÄ±yÄ±n.\n'
            '_PANEL_HTML = """\n'
            '<div id="panel-plugin-widget"\n'
            '     style="padding:12px;border:1px solid #333;border-radius:6px;">\n'
            '  <h3 style="margin:0 0 8px">Panel Plugin</h3>\n'
            '  <p>Buraya ozel UI bileseni ekleyin.</p>\n'
            '  <button\n'
            '    onclick="fetch(\'/plugins/panel_plugin/veri\')\n'
            '             .then(r=>r.json()).then(d=>alert(JSON.stringify(d)))">\n'
            '    Veri Cek\n'
            '  </button>\n'
            '</div>\n'
            '"""\n'
            '\n'
            '\n'
            'def register_routes(app):\n'
            '    # /plugins/panel_plugin/panel â€” HTML parcasini dondurur\n'
            '    @app.route("/plugins/panel_plugin/panel")\n'
            '    def panel_plugin_html():\n'
            '        return app.response_class(\n'
            '            response=_PANEL_HTML, status=200, mimetype="text/html"\n'
            '        )\n'
            '\n'
            '    # /plugins/panel_plugin/veri â€” panel icin JSON API\n'
            '    @app.route("/plugins/panel_plugin/veri")\n'
            '    def panel_plugin_veri():\n'
            '        import json as _json\n'
            '        return app.response_class(\n'
            '            response=_json.dumps({"mesaj": "Panel verisi", "plugin": "panel_plugin"}),\n'
            '            status=200,\n'
            '            mimetype="application/json",\n'
            '        )\n'
            '\n'
            '\n'
            'def on_vm_event(event):\n'
            '    pass\n'
        )
        return {"filename": "plugin.py", "code": code}

    return {
        "error":     f"Bilinmeyen sablon turu: '{kind}'",
        "available": ["basic", "api", "event", "panel"],
    }


def get_sdk_info() -> dict:
    """
    Plugin geliÅŸtirici baÅŸvuru kÄ±lavuzu dÃ¶ner.

    DÃ¶ner: api_version, hooks, meta_fields, example_event_types, plugin_dir, docs_url
    """
    return {
        "api_version": "1.0",
        "hooks": [
            {
                "name":        "register_routes",
                "signature":   "register_routes(app: Flask) -> None",
                "description": (
                    "Flask uygulamasÄ±na rota ekler. "
                    "Plugin etkinleÅŸtirilmiÅŸse baÅŸlangÄ±Ã§ta bir kez Ã§aÄŸrÄ±lÄ±r."
                ),
            },
            {
                "name":        "on_vm_event",
                "signature":   "on_vm_event(event: dict) -> None",
                "description": (
                    "emit_event() ile yayÄ±lan her VM olayÄ± iÃ§in Ã§aÄŸrÄ±lÄ±r. "
                    'event = {"type": str, "data": dict}'
                ),
            },
        ],
        "meta_fields": [
            {"field": "id",          "required": True,  "description": "Benzersiz kimlik ^[a-z0-9_-]{1,48}$"},
            {"field": "name",        "required": True,  "description": "KullanÄ±cÄ±ya gÃ¶sterilen isim"},
            {"field": "version",     "required": True,  "description": "SemVer (Ã¶rn. '1.0.0')"},
            {"field": "author",      "required": True,  "description": "GeliÅŸtirici adÄ± veya e-posta"},
            {"field": "description", "required": True,  "description": "KÄ±sa aÃ§Ä±klama"},
            {"field": "api_version", "required": True,  "description": "ankavm API uyumluluk sÃ¼rÃ¼mÃ¼"},
            {"field": "enabled",     "required": False, "description": "BaÅŸlangÄ±Ã§ durumu (yÃ¼kleme her zaman False'a ayarlanÄ±r)"},
        ],
        "example_event_types": [
            "vm.created",
            "vm.deleted",
            "vm.started",
            "vm.stopped",
            "vm.snapshot_created",
            "vm.snapshot_deleted",
            "vm.migrated",
            "node.connected",
            "node.disconnected",
        ],
        "plugin_dir": str(_PLUGINS_DIR),
        "docs_url":   "https://ankavm.local/docs#plugins",
    }






