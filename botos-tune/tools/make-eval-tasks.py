#!/usr/bin/env python
"""Turn the held-out test split into a `soup eval custom` task file (Phase 3).

Input rows are botos2jsonl rows (messages + meta). Output rows:
    {"prompt": "<system + conversation up to the last user turn>",
     "expected": "<gold assistant answer>", "category": "<meta.class>", "scoring": "<mode>"}

Scoring per class: extract -> "answer" when the gold is JSON (exact after whitespace/keys
normalisation is what Soup applies), else "contains"; classify -> "regex" anchored on the gold
label; everything else -> "contains".

    python tools\\make-eval-tasks.py data\\test.jsonl -o evals\\botos-tasks.jsonl
        [--classes extract,classify]
"""

from __future__ import annotations

import argparse
import json
import re
import sys


def _is_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def render_prompt(messages: list[dict]) -> str:
    """Flatten everything before the final assistant turn into one prompt string."""
    parts = []
    for m in messages[:-1]:
        role = m.get("role", "user")
        content = m.get("content") or ""
        if role == "tool":
            content = f"[tool result]\n{content}"
        if m.get("tool_calls"):
            calls = "; ".join(
                f"{c.get('function', {}).get('name', '?')}"
                f"({c.get('function', {}).get('arguments', '')[:200]})"
                for c in m["tool_calls"]
            )
            content = (content + "\n" if content else "") + f"[tool calls] {calls}"
        parts.append(f"{role.upper()}: {content}")
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--classes", default="extract,classify")
    ap.add_argument("--max-prompt-chars", type=int, default=12000)
    a = ap.parse_args()
    keep = {c.strip() for c in a.classes.split(",") if c.strip()}
    n = 0
    with open(a.path, encoding="utf-8") as fi, open(a.out, "w", encoding="utf-8") as fo:
        for line in fi:
            if not line.strip():
                continue
            row = json.loads(line)
            cls = row.get("meta", {}).get("class", "draft")
            if keep and cls not in keep:
                continue
            last = row["messages"][-1]
            if last.get("role") != "assistant" or last.get("tool_calls"):
                continue
            gold = (last.get("content") or "").strip()
            if not gold:
                continue
            if cls == "classify":
                m = re.search(r"\bL[0-6]\b", gold)
                task = {
                    "expected": re.escape(m.group(0)) if m else re.escape(gold[:80]),
                    "scoring": "regex",
                }
            elif cls == "extract" and _is_json(gold):
                task = {"expected": gold, "scoring": "answer"}
            else:
                task = {"expected": gold[:200], "scoring": "contains"}
            prompt = render_prompt(row["messages"])[-a.max_prompt_chars :]
            fo.write(
                json.dumps({"prompt": prompt, "category": cls, **task}, ensure_ascii=False) + "\n"
            )
            n += 1
    print(f"wrote {n} tasks -> {a.out}")
    return 0 if n else 2


if __name__ == "__main__":
    sys.exit(main())
