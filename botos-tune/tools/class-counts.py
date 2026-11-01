#!/usr/bin/env python
"""Rows per meta.class / meta.source in a botos2jsonl output, and whether the Phase 1 bar is met.

python tools\\class-counts.py data\\train.jsonl [--min 300]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

IN_SCOPE = ("extract", "classify")  # v0.1 classes (roadmap: decisions already taken)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--min", type=int, default=300, help="rows per in-scope class")
    a = ap.parse_args()
    by_class: Counter[str] = Counter()
    by_pair: Counter[str] = Counter()
    n = 0
    with open(a.path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            meta = json.loads(line).get("meta", {})
            n += 1
            by_class[meta.get("class", "?")] += 1
            by_pair[f"{meta.get('source', '?')}/{meta.get('class', '?')}"] += 1
    print(f"{n} rows")
    for k, v in sorted(by_class.items()):
        print(f"  {k:10s} {v:6d}")
    print("by source:")
    for k, v in sorted(by_pair.items()):
        print(f"  {k:28s} {v:6d}")
    ok = True
    for c in IN_SCOPE:
        if by_class[c] < a.min:
            ok = False
            print(
                f"THIN: {c} has {by_class[c]} < {a.min}; top up with "
                f"`soup data generate --provider ollama --template qa` or more sources"
            )
    print("Phase 1 bar:", "MET" if ok else "NOT MET")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
