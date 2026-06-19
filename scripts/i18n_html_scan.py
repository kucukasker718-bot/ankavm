#!/usr/bin/env python3
"""Scan index.html body for Turkish text nodes that are NOT yet in PAGE_STRINGS.

We do a lightweight HTML walk (regex-based, no external deps) to extract every
visible text node inside the <body>. Anything containing Turkish-specific
letters (ÄŸ/ÅŸ/Ä±/Ä°/Ã§/Ã¶/Ã¼/Ä/Å/Ã‡/Ã–/Ãœ) or a known TR word is a candidate. We then
diff against PAGE_STRINGS.en keys (extracted by i18n_extract.py) and write the
missing ones to tmp_i18n/missing_html_tr.txt for translation.

Run:
    python scripts/i18n_extract.py          # produces tmp_i18n/en.json
    python scripts/i18n_html_scan.py        # produces tmp_i18n/missing_html_tr.txt
"""
from __future__ import annotations
import html
import json
import os
import re

SRC = "ankavm/frontend/templates/index.html"
OUT_DIR = "tmp_i18n"

TR_CHARS = set("Ã§ÄŸÄ±Ä°Ã¶ÅŸÃ¼Ã‡ÄIÃ–ÅÃœ")
TR_HINT_WORDS = {
    "ve", "veya", "ile", "iÃ§in", "olarak", "bir", "bu", "ÅŸu", "ben",
    "yeni", "ekle", "sil", "kaydet", "iptal", "kapat", "dÃ¼zenle",
    "oluÅŸtur", "yÃ¼kle", "indir", "yenile", "ara", "ayar", "ayarlar",
    "kullanÄ±cÄ±", "kullanÄ±cÄ±lar", "ÅŸifre", "yÃ¶netici", "rol", "grup",
    "aÄŸ", "aÄŸÄ±", "aÄŸa", "aÄŸdan", "depolama", "yedek", "yedekleme",
    "izleme", "uyarÄ±", "olay", "gÃ¼nlÃ¼k", "geÃ§miÅŸ", "rapor", "yedek",
    "sistem", "donanÄ±m", "yazÄ±lÄ±m", "bilgi", "durum", "boÅŸ", "dolu",
    "aÃ§Ä±k", "kapalÄ±", "evet", "hayÄ±r", "tamam", "vazgeÃ§", "geri",
    "ileri", "Ã¶nceki", "sonraki", "varsayÄ±lan", "Ã¶zel", "genel",
    "sanal", "makine", "makineler", "anlÄ±k", "gÃ¶rÃ¼ntÃ¼",
}


def looks_turkish(s: str) -> bool:
    s = s.strip()
    if len(s) < 2:
        return False
    # Pure ASCII numeric / symbol â†’ skip
    if not any(c.isalpha() for c in s):
        return False
    # Has TR-specific letters â†’ Turkish
    if any(c in TR_CHARS for c in s):
        return True
    # Has TR hint words (lowercased token match)
    tokens = re.findall(r"[A-Za-zÃ§ÄŸÄ±Ä°Ã¶ÅŸÃ¼Ã‡ÄIÃ–ÅÃœ]+", s.lower())
    if any(t in TR_HINT_WORDS for t in tokens):
        return True
    return False


def extract_body(html_src: str) -> str:
    m = re.search(r"<body[^>]*>([\s\S]*?)</body>", html_src, re.I)
    return m.group(1) if m else html_src


def strip_block(html_body: str, tag: str) -> str:
    return re.sub(rf"<{tag}\b[^>]*>[\s\S]*?</{tag}>", "", html_body, flags=re.I)


def text_nodes(html_body: str):
    # Strip <script>, <style>, <noscript>, <template>, <svg> contents â€” we only
    # want presentational text. The big inline <script>s carry the PAGE_STRINGS
    # dict itself, so leaving them in would pollute the scan.
    cleaned = html_body
    for t in ("script", "style", "noscript", "template", "svg", "math"):
        cleaned = strip_block(cleaned, t)
    # Now split on tags â€” what's outside tags is text content.
    out = []
    pos = 0
    for m in re.finditer(r"<[^>]+>", cleaned):
        chunk = cleaned[pos:m.start()]
        pos = m.end()
        if chunk.strip():
            out.append(chunk)
    if pos < len(cleaned):
        chunk = cleaned[pos:]
        if chunk.strip():
            out.append(chunk)
    # Also catch attribute strings worth translating: placeholder=, title=, aria-label=
    for m in re.finditer(
        r'(?:placeholder|title|aria-label|alt)\s*=\s*"([^"]+)"',
        cleaned,
        re.I,
    ):
        out.append(m.group(1))
    return out


def clean_text(t: str) -> str:
    t = html.unescape(t)
    # Collapse internal whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    src = open(SRC, encoding="utf-8").read()
    body = extract_body(src)
    nodes = text_nodes(body)
    seen = set()
    candidates = []
    for raw in nodes:
        t = clean_text(raw)
        if not t or t in seen:
            continue
        seen.add(t)
        if looks_turkish(t):
            candidates.append(t)

    # Diff against existing PAGE_STRINGS.en keys
    en_path = os.path.join(OUT_DIR, "en.json")
    have = set()
    if os.path.exists(en_path):
        have = set(json.load(open(en_path, encoding="utf-8")).keys())
    missing = sorted(c for c in candidates if c not in have)

    out_path = os.path.join(OUT_DIR, "missing_html_tr.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        for k in missing:
            f.write(k + "\n")

    print(f"Total text nodes scanned: {len(seen)}")
    print(f"Turkish-looking strings: {len(candidates)}")
    print(f"Already in PAGE_STRINGS.en: {len(candidates) - len(missing)}")
    print(f"Missing -> {out_path}: {len(missing)}")


if __name__ == "__main__":
    main()






