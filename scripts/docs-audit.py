#!/usr/bin/env python3
"""Lightweight docs audit: broken relative links, metrics, drift facts.

Stdlib only. Informational by design — it reports, it never rewrites.
Exit code 1 only on broken relative links.
"""
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "node_modules", "__pycache__", "archive"}
MD_EXT = (".md", ".mdx")

# High-drift facts: report which docs mention them (informational only).
DRIFT_FACTS = [
    r"\b7860\b", r"\b9091\b", r"\b6080\b", r"\b5901\b", r"\b8648\b",
    r"/mnt/workspace[/\w-]*",
    r"\b(?:PUBLIC_ORIGIN|AUTH_PASSWORD|VNC_PASSWORD|DESKTOP_PASSWORD|"
    r"OPENAI_BASE_URL|OPENAI_API_KEY|HERMES_MODEL|DATA_ROOT|CHROME_NO_SANDBOX)\b",
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def md_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(MD_EXT):
                yield os.path.join(dirpath, fn)


def check_links(path, text):
    broken = []
    base = os.path.dirname(path)
    for target in LINK_RE.findall(text):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        clean = urllib.parse.unquote(target.split("#")[0])
        if not clean:
            continue
        resolved = os.path.normpath(os.path.join(base, clean))
        if not os.path.exists(resolved):
            broken.append((os.path.relpath(path, ROOT), target))
    return broken


def main():
    files = list(md_files())
    broken_all, drift = [], {}
    print(f"{'file':<50} {'lines':>6} {'chars':>7} {'heads':>5}")
    for path in sorted(files):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        rel = os.path.relpath(path, ROOT)
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        heads = len(re.findall(r"^#{1,6} ", text, re.M))
        print(f"{rel:<50} {lines:>6} {len(text):>7} {heads:>5}")
        broken_all += check_links(path, text)
        for fact in DRIFT_FACTS:
            if re.search(fact, text):
                drift.setdefault(fact, []).append(rel)

    print("\n== high-drift facts (informational: confirm single source) ==")
    for fact, locs in sorted(drift.items(), key=lambda kv: -len(kv[1])):
        marker = " <-- duplicated" if len(locs) > 1 else ""
        print(f"  {fact:<60} {len(locs)} file(s): {', '.join(locs)}{marker}")

    if broken_all:
        print("\n== BROKEN LINKS ==")
        for rel, target in broken_all:
            print(f"  {rel}: {target}")
        return 1
    print("\nlinks: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
