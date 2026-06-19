#!/usr/bin/env python3
"""Rewrite the ES/DE/ZH blocks inside PAGE_STRINGS using tmp_i18n/{lang}_full.json.

This finds each `  <lang>: {` block in index.html, replaces its body with one
JS entry per TR key, and writes the file back.

Run after i18n_extract.py and i18n_translate.py.
"""
from __future__ import annotations
import json
import os
import re

SRC = "ankavm/frontend/templates/index.html"
OUT_DIR = "tmp_i18n"


def find_block_bounds(lines, lang_name, after_marker="const PAGE_STRINGS"):
    """Return (start_line_idx, end_line_idx) of `  <lang>: {` block inside the
    PAGE_STRINGS dict. We anchor the search to the line containing
    `const PAGE_STRINGS = {` to avoid colliding with the smaller LANGS dict
    above (which has identical `  <lang>: {` headers)."""
    pattern = re.compile(rf"^  {lang_name}: \{{")
    anchor = None
    for i, ln in enumerate(lines):
        if after_marker in ln:
            anchor = i
            break
    if anchor is None:
        return None, None
    for i in range(anchor, len(lines)):
        if pattern.match(lines[i]):
            depth = 0
            started = False
            for j in range(i, len(lines)):
                for ch in lines[j]:
                    if ch == "{":
                        depth += 1
                        started = True
                    elif ch == "}":
                        depth -= 1
                        if started and depth == 0:
                            return i, j
    return None, None


def js_escape(s: str) -> str:
    # Single-quoted JS string. Escape: backslash, single quote, newline, CR.
    return (s.replace("\\", "\\\\")
              .replace("'", "\\'")
              .replace("\n", "\\n")
              .replace("\r", "\\r"))


def render_block(lang_name, entries):
    """Return a list of lines for the lang block."""
    lines = [f"  {lang_name}: {{"]
    # Sort entries by key for deterministic output
    for k in sorted(entries.keys()):
        v = entries[k]
        lines.append(f"    '{js_escape(k)}':'{js_escape(v)}',")
    lines.append("  },")
    return lines


def main():
    with open(SRC, encoding="utf-8") as f:
        src = f.read()
    lines = src.split("\n")

    # Replace in reverse order so earlier line numbers stay valid
    for lang in ("fr", "zh", "de", "es", "en"):
        # Prefer _full.json (augmented) if present, else fall back to raw.
        full_path = f"{OUT_DIR}/{lang}_full.json"
        if not os.path.exists(full_path):
            full_path = f"{OUT_DIR}/{lang}.json"
        full = json.load(open(full_path, encoding="utf-8"))
        start, end = find_block_bounds(lines, lang)
        if start is None:
            print(f"!! {lang}: block not found, skipping")
            continue
        new_lines = render_block(lang, full)
        lines[start:end + 1] = new_lines
        print(f"{lang}: replaced lines {start + 1}..{end + 1} with {len(new_lines)} lines"
              f" ({len(full)} entries)")

    with open(SRC, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("OK injected")


if __name__ == "__main__":
    main()






