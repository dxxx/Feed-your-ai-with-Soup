#!/usr/bin/env python
"""Print every client domain found in a Work Brain vault, one per line, for deny-list.txt.

Reads note file names and `client:` / `domain:` front-matter keys under Clients/, Cases/ and
Projects/. Stdlib only.

    python tools\\make-deny-list.py "E:\\BRAINS-MEMMORIES\\WORK_BRAIN" >> deny-list.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOMAIN = re.compile(
    r"\b([a-z0-9][a-z0-9\-]{1,62}\.(?:[a-z]{2,}|co\.[a-z]{2}|com\.[a-z]{2}))\b", re.I
)
KEY = re.compile(r"(?im)^(?:client|domain|site|url)\s*:\s*[\"']?([^\s\"']+)")
SKIP = {
    "github.com",
    "claude.ai",
    "anthropic.com",
    "google.com",
    "obsidian.md",
    "trysoup.dev",
    "botos.md",
    "fiverr.com",
    "wordpress.org",
    "joomla.org",
    "huggingface.co",
    "ollama.com",
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    vault = Path(sys.argv[1])
    found: set[str] = set()
    for sub in ("Clients", "Cases", "Projects", "Work History"):
        for p in (vault / sub).rglob("*.md"):
            for m in DOMAIN.finditer(p.stem):
                found.add(m.group(1).lower())
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:1500]
            except OSError:
                continue
            for m in KEY.finditer(head):
                v = m.group(1).strip().lower().removeprefix("https://").removeprefix("http://")
                if DOMAIN.fullmatch(v.split("/")[0]):
                    found.add(v.split("/")[0])
    for d in sorted(found - SKIP):
        print(d)
    print(f"# {len(found - SKIP)} domains", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
