"""ankavm VM Notes Manager â€” /var/lib/ankavm/vm_notes.json"""
import json, threading, re
from pathlib import Path
from datetime import datetime

_NOTES_FILE = "/var/lib/ankavm/vm_notes.json"
_lock = threading.Lock()

# rapor #62 fix: stored XSS â€” HTML tehlikeli taglarÄ± strip et
_TAG_RE  = re.compile(r"<(script|style|iframe|object|embed|form|input|button|link|meta)[^>]*>.*?</\1>",
                      re.IGNORECASE | re.DOTALL)
_TAG_ALL = re.compile(r"<[^>]+>")

def _sanitize_note(content: str) -> str:
    """Strip script/iframe/style tags, then strip remaining HTML tags."""
    content = _TAG_RE.sub("", content)
    content = _TAG_ALL.sub("", content)
    return content[:10000]

def _load():
    try:
        p = Path(_NOTES_FILE)
        if p.exists(): return json.loads(p.read_text())
    except Exception: pass
    return {}

def _save(data):
    Path(_NOTES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(_NOTES_FILE).write_text(json.dumps(data, indent=2))

def get_note(vm_id):
    with _lock: return _load().get(str(vm_id))

def save_note(vm_id, content):
    content = _sanitize_note(str(content))
    entry = {"content": content, "updated_at": datetime.now().isoformat()}
    with _lock:
        d = _load(); d[str(vm_id)] = entry; _save(d)
    return entry

def delete_note(vm_id):
    with _lock:
        d = _load(); d.pop(str(vm_id), None); _save(d)






