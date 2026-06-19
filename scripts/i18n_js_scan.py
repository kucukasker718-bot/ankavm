#!/usr/bin/env python3
"""Scan inline JS in index.html for TR string literals that are NOT in
PAGE_STRINGS. Common offenders: toast('...'), confirm('...'),
prompt('...'), alert('...'), and showError('...').

Run after i18n_extract.py.
Output: tmp_i18n/missing_js_tr.txt
"""
from __future__ import annotations
import json
import os
import re

SRC = "ankavm/frontend/templates/index.html"
OUT_DIR = "tmp_i18n"

TR_CHARS = set("Ã§ÄŸÄ±Ä°Ã¶ÅŸÃ¼Ã‡ÄIÃ–ÅÃœ")
CALL_PATTERN = re.compile(
    r"(?:toast|confirm|prompt|alert|showError|showInfo|showWarn|"
    r"showSuccess|_t|t)\(\s*(['\"])([^'\"\\]*(?:\\.[^'\"\\]*)*)\1",
    re.M,
)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    src = open(SRC, encoding="utf-8").read()
    candidates = set()
    for m in CALL_PATTERN.finditer(src):
        s = m.group(2)
        if any(c in TR_CHARS for c in s):
            candidates.add(s)
    en = {}
    en_path = os.path.join(OUT_DIR, "en.json")
    if os.path.exists(en_path):
        en = json.load(open(en_path, encoding="utf-8"))
    missing = sorted(c for c in candidates if c not in en)
    out_path = os.path.join(OUT_DIR, "missing_js_tr.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        for k in missing:
            f.write(k + "\n")
    print(f"JS calls scanned: {len(candidates)} TR-looking literals")
    print(f"Missing -> {out_path}: {len(missing)}")
    return 0 if not missing else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())






