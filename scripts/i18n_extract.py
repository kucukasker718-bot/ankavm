#!/usr/bin/env python3
"""Extract PAGE_STRINGS per-language dicts from index.html into JSON files.

Usage: python scripts/i18n_extract.py
Outputs: tmp_i18n/en.json, tmp_i18n/es.json, tmp_i18n/de.json, tmp_i18n/zh.json
         tmp_i18n/missing_es.txt, tmp_i18n/missing_de.txt, tmp_i18n/missing_zh.txt
"""
from __future__ import annotations
import json
import os
import re
import sys

SRC = "ankavm/frontend/templates/index.html"
OUT_DIR = "tmp_i18n"
LANGS = ("en", "es", "de", "zh", "fr")


def find_block_bounds(lines, lang_name, after_marker="const PAGE_STRINGS"):
    """Locate `  <lang>: {` block inside PAGE_STRINGS (skipping LANGS dict)."""
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
                            return i + 1, j + 1
    return None, None


def extract_block(lines, lang):
    s, e = find_block_bounds(lines, lang)
    if s is None:
        return None, None
    return e, "\n".join(lines[s - 1:e])


def parse_entries(block_text):
    body = block_text.split("{", 1)[1].rsplit("}", 1)[0]
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    out = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        q = body[i]
        if q not in ("'", '"'):
            i += 1
            continue
        i += 1
        s = []
        while i < n and body[i] != q:
            if body[i] == "\\" and i + 1 < n:
                s.append(body[i + 1])
                i += 2
            else:
                s.append(body[i])
                i += 1
        key = "".join(s)
        i += 1
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n or body[i] != ":":
            continue
        i += 1
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n or body[i] not in ("'", '"'):
            continue
        q2 = body[i]
        i += 1
        v = []
        while i < n and body[i] != q2:
            if body[i] == "\\" and i + 1 < n:
                v.append(body[i + 1])
                i += 2
            else:
                v.append(body[i])
                i += 1
        val = "".join(v)
        i += 1
        out.append((key, val))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SRC, encoding="utf-8") as f:
        lines = f.read().split("\n")
    results = {}
    for lang in LANGS:
        end, text = extract_block(lines, lang)
        if text is None:
            print(f"{lang}: BLOCK NOT FOUND")
            results[lang] = {}
            continue
        entries = parse_entries(text)
        results[lang] = dict(entries)
        json.dump(results[lang], open(f"{OUT_DIR}/{lang}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2, sort_keys=True)
        print(f"{lang}: {len(entries)} entries (block ends line {end})")
    en_keys = set(results["en"].keys())
    for lang in ("es", "de", "zh", "fr"):
        missing = sorted(en_keys - set(results[lang].keys()))
        with open(f"{OUT_DIR}/missing_{lang}.txt", "w", encoding="utf-8") as f:
            for k in missing:
                f.write(k + "\t" + results["en"].get(k, "") + "\n")
        print(f"{lang} missing {len(missing)}/{len(en_keys)} entries")


if __name__ == "__main__":
    main()






