#!/usr/bin/env python3
"""One-shot i18n refresh: extract → html scan → js scan → augment → inject.

Run after any UI change. Designed to be called from the Makefile
(`make i18n`) and from CI. Exits non-zero if missing strings remain
after the augment pass — that means a new TR string was hardcoded with
no curated translation and the EN_FALLBACK path was taken; the
maintainer should add an explicit translation to
scripts/i18n_translate.py (and i18n_augment.py for TR→EN) before
merging.
"""
from __future__ import annotations
import subprocess
import sys


def run(name):
    print(f"\n-- {name} --")
    r = subprocess.run([sys.executable, f"scripts/{name}.py"])
    return r.returncode


def main():
    # First pass: extract baseline + detect gaps.
    run("i18n_extract")
    run("i18n_html_scan")
    run("i18n_js_scan")
    # Augment + inject: fill the gaps.
    rc_aug = run("i18n_augment")
    rc_inj = run("i18n_inject")
    # Verification pass: extract again + rescan. Now the gap files should be
    # empty because augment+inject added the missing entries.
    run("i18n_extract")
    rc_html = run("i18n_html_scan")
    rc_js = run("i18n_js_scan")
    rc = rc_aug | rc_inj | rc_html | rc_js
    print(f"\nPipeline finished, verification rc={rc}")
    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()






