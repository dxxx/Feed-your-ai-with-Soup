#!/usr/bin/env python
"""botos2jsonl - turn Bot-OS memory + Work Brain notes + Claude Code transcripts into Soup JSONL.

Stdlib only (Python 3.11+). One source adapter per memory type; every adapter yields rows of
the shape Soup's `chatml` / `tool-calling` loaders read:

    {"messages": [{"role": "system"|"user"|"assistant"|"tool", "content": "..."}],
     "meta": {"class": "extract|classify|reformat|draft|code|tool",
              "source": "claude_code|cards|adr|brain_cases|evalkit",
              "path": "...", "date": "YYYY-MM-DD", "sha": "..."}}

Rows whose assistant answer was later rejected (next user turn says "no / wrong / fix ...") go
to --rejected instead of --out, so Phase 5 (DPO) can pair them.

A scrub pass runs on every turn before it is written (secrets, emails, IPs, deny-listed
domains). Paths matching --drop-pattern (default: the medical vault) are never read.

Usage (PowerShell, RYZEN9):
    python tools\\botos2jsonl.py --out data\\raw.jsonl --rejected data\\rejected.jsonl ^
        --deny-list deny-list.txt ^
        --claude-code "$env:USERPROFILE\\.claude\\projects" ^
        --cards "C:\\Users\\dXXX\\Desktop\\Bot-OS\\Bot-OS\\done" "...\\retros" ^
        --adr   "C:\\Users\\dXXX\\Desktop\\Bot-OS\\Bot-OS\\decisions" ^
        --brain-cases "E:\\BRAINS-MEMMORIES\\WORK_BRAIN\\Cases" ^
        --evalkit "E:\\Local-AI\\botos-local-eval\\suites"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CLASSES = ("extract", "classify", "reformat", "draft", "code", "tool")

# --------------------------------------------------------------------------- scrub

SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_KEY]"),
    (r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}\b", "[REDACTED_TOKEN]"),
    (r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b", "[REDACTED_TOKEN]"),
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "[REDACTED_TOKEN]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
    (r"\bxox[abp]-[A-Za-z0-9\-]{10,}\b", "[REDACTED_TOKEN]"),
    (r"\bhf_[A-Za-z0-9]{20,}\b", "[REDACTED_TOKEN]"),
    (r"(?i)\b(bearer)\s+[A-Za-z0-9_\-\.=]{16,}", r"\1 [REDACTED_TOKEN]"),
    (
        r"(?i)\b(pass(?:word|wd|phrase)?|secret|token|api[_\-]?key|auth)\s*[:=]\s*['\"]?"
        r"[^\s'\"]{6,}",
        r"\1=[REDACTED]",
    ),
    (r"(?i)\b(mysql|psql|ssh|sshpass)\b[^\n]*?(-p|--password[= ])\s*\S+", r"\1 \2 [REDACTED]"),
    (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[EMAIL]"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]"),
    (r"(?i)P:\\\.key\\[^\s\"']*", "P:\\.key\\[FILE]"),
]

_COMPILED = [(re.compile(p, re.S), r) for p, r in SECRET_PATTERNS]


@dataclass
class Scrubber:
    deny_domains: list[str] = field(default_factory=list)
    hits: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._deny = [
            # no word boundaries on purpose: a client domain must vanish even inside
            # JSON-escaped or path-joined text ("\\nclient.com", "client.com\\Bot-OS")
            re.compile(r"(?i)" + re.escape(d.lower()))
            for d in self.deny_domains
            if d
        ]

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for rx, rep in _COMPILED:
            text, n = rx.subn(rep, text)
            if n:
                self.hits[rx.pattern[:30]] = self.hits.get(rx.pattern[:30], 0) + n
        for rx in self._deny:
            text, n = rx.subn("[CLIENT_DOMAIN]", text)
            if n:
                self.hits["deny-list"] = self.hits.get("deny-list", 0) + n
        return text


def scrub_obj(obj, scrub: Scrubber):
    """Scrub every string inside a nested dict/list (tool inputs) before JSON-encoding."""
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, list):
        return [scrub_obj(x, scrub) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub_obj(v, scrub) for k, v in obj.items()}
    return obj


def load_deny_list(path: str | None) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


# --------------------------------------------------------------------------- classes

_CLASS_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "classify",
        re.compile(
            r"(?i)\b(classif|which (?:level|class|tier|category)|L[0-6]\b|label (?:this|each)|"
            r"categori[sz]e|is (?:this|it) (?:a|an) )"
        ),
    ),
    (
        "extract",
        re.compile(
            r"(?i)\b(extract|pull out|list (?:all|every)|find (?:all|every)|which files|"
            r"inventory|what (?:are|is) the .* in (?:this|the) (?:file|log|note)|as json|"
            r"return json|json only)"
        ),
    ),
    (
        "reformat",
        re.compile(
            r"(?i)\b(reformat|convert (?:this|it|to)|rewrite (?:as|into|in)|turn (?:this|it) into|"
            r"as a table|as markdown|summari[sz]e|shorten|tidy)"
        ),
    ),
]
_CODE_FENCE = re.compile(
    r"```(?:python|bash|sh|powershell|ps1|js|javascript|ts|php|sql|yaml|json)?\n"
)


def guess_class(user_text: str, assistant: dict) -> str:
    if assistant.get("tool_calls"):
        return "tool"
    for name, rx in _CLASS_RULES:
        if rx.search(user_text or ""):
            return name
    content = assistant.get("content") or ""
    if _CODE_FENCE.search(content) and len(content) > 200:
        return "code"
    return "draft"


_REJECT = re.compile(
    r"(?i)^\s*(no\b|nope|wrong|incorrect|that'?s (?:not|wrong)|not (?:right|correct|what)|"
    r"fix (?:this|that|it)|try again|redo|you (?:missed|broke|forgot)|doesn'?t work|"
    r"still (?:fails|broken|wrong))"
)


def looks_rejected(next_user_text: str | None) -> bool:
    return bool(next_user_text and _REJECT.search(next_user_text))


# --------------------------------------------------------------------------- helpers


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def _date_of(path: Path, fallback: str | None = None) -> str:
    m = re.search(r"(20\d\d-\d\d-\d\d)", path.name)
    if m:
        return m.group(1)
    if fallback:
        return fallback[:10]
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return "unknown"


def _row(
    messages: list[dict],
    cls: str,
    source: str,
    path: Path,
    date: str,
    extra: dict | None = None,
    tools: list | None = None,
) -> dict:
    meta = {
        "class": cls,
        "source": source,
        "path": str(path),
        "date": date,
        "sha": _sha(json.dumps(messages, ensure_ascii=False, sort_keys=True)),
        "risk": "L1",
    }
    if extra:
        meta.update(extra)
    # `cls` is duplicated at top level so `soup data split --stratify cls` can see it
    row: dict = {"messages": messages, "meta": meta, "cls": cls}
    if tools:
        row["tools"] = tools
    return row


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + "\n[...clipped...]\n" + text[-(limit - head) :]


def iter_files(
    dirs: Iterable[str], suffixes: tuple[str, ...], drop: re.Pattern[str] | None
) -> Iterator[Path]:
    for d in dirs:
        root = Path(d)
        if root.is_file():
            cands = [root]
        elif root.is_dir():
            cands = sorted(p for p in root.rglob("*") if p.is_file())
        else:
            print(f"  ! skip missing: {d}", file=sys.stderr)
            continue
        for p in cands:
            if p.suffix.lower() not in suffixes:
                continue
            if drop and drop.search(str(p)):
                continue
            yield p


# --------------------------------------------------------------------------- adapter: claude_code


def _text_of_blocks(content) -> tuple[str, list[dict], list[dict]]:
    """Return (text, tool_uses, tool_results) from a Claude message content."""
    if isinstance(content, str):
        return content, [], []
    text_parts, uses, results = [], [], []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            text_parts.append(b.get("text", ""))
        elif t == "tool_use":
            uses.append(b)
        elif t == "tool_result":
            results.append(b)
    return "\n".join(tp for tp in text_parts if tp), uses, results


def _tool_result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    out = []
    for part in c or []:
        if isinstance(part, dict) and part.get("type") == "text":
            out.append(part.get("text", ""))
    return "\n".join(out)


_SYSTEM_NOISE2 = re.compile(
    r"<system-reminder>.*?</system-reminder>|<local-command-stdout>.*?</local-command-stdout>"
    r"|<local-command-caveat>.*?</local-command-caveat>|<command-(?:name|message|args)>.*?"
    r"</command-(?:name|message|args)>",
    re.S,
)


def _clean_user(text: str) -> str:
    text = _SYSTEM_NOISE2.sub("", text)
    return text.strip()


def adapt_claude_code(
    paths: Iterable[Path],
    scrub: Scrubber,
    *,
    context_turns: int,
    max_turn_chars: int,
    max_tool_chars: int,
    include_tools: bool,
    skip_sidechain: bool,
) -> Iterator[tuple[dict, bool]]:
    for p in paths:
        turns: list[dict] = []  # flat chat: {"role","content"[,"tool_calls"|"tool_call_id"]}
        session_date = None
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t not in ("user", "assistant"):
                continue
            if skip_sidechain and d.get("isSidechain"):
                continue
            session_date = session_date or d.get("timestamp")
            m = d.get("message") or {}
            text, uses, results = _text_of_blocks(m.get("content"))
            if t == "user":
                for r in results:
                    turns.append(
                        {
                            "role": "tool",
                            "tool_call_id": r.get("tool_use_id", ""),
                            "content": _clip(scrub(_tool_result_text(r)), max_tool_chars),
                        }
                    )
                text = _clean_user(text)
                if text and not text.startswith("[Request interrupted"):
                    turns.append({"role": "user", "content": scrub(_clip(text, max_turn_chars))})
            else:
                a: dict = {"role": "assistant", "content": scrub(_clip(text, max_turn_chars))}
                if uses and include_tools:
                    a["tool_calls"] = [
                        {
                            "id": u.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": u.get("name", ""),
                                "arguments": _clip(
                                    scrub(
                                        json.dumps(
                                            scrub_obj(u.get("input", {}), scrub), ensure_ascii=False
                                        )
                                    ),
                                    max_tool_chars,
                                ),
                            },
                        }
                        for u in uses
                    ]
                if a["content"] or a.get("tool_calls"):
                    turns.append(a)
        date = _date_of(p, session_date)
        # one row per assistant turn, with a window of preceding turns as context
        user_idx = [i for i, tr in enumerate(turns) if tr["role"] == "user"]
        for i, tr in enumerate(turns):
            if tr["role"] != "assistant":
                continue
            prev_users = [u for u in user_idx if u < i]
            if not prev_users:
                continue
            start = max(0, i - context_turns)
            # never start a window on a tool result without its call
            while start < i and turns[start]["role"] == "tool":
                start += 1
            window = turns[start:i]
            if not any(w["role"] == "user" for w in window):
                window = [turns[prev_users[-1]]] + window
            msgs = window + [tr]
            last_user = turns[prev_users[-1]]["content"]
            # the next user turn judges THIS answer only if no later assistant turn sits between
            nxt = None
            for j in range(i + 1, len(turns)):
                if turns[j]["role"] == "assistant":
                    break
                if turns[j]["role"] == "user":
                    nxt = turns[j]["content"]
                    break
            cls = guess_class(last_user, tr)
            if cls == "tool" and not tr["content"]:
                # pure tool-call turn: keep it only as a tool row with a non-empty prompt
                pass
            yield (
                _row(msgs, cls, "claude_code", p, date, {"session": p.stem, "turn": i}),
                looks_rejected(nxt),
            )


# --------------------------------------------------------------------------- markdown adapters

_H = re.compile(r"^(#{1,6})\s+(.*)$", re.M)


def md_sections(text: str) -> list[tuple[str, str]]:
    """[(heading, body)] with a leading ("", preamble) when text precedes the first heading."""
    # strip YAML front matter
    fm = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[: end + 4]
            text = text[end + 4 :]
    parts = []
    last_end, last_head = 0, ""
    for m in _H.finditer(text):
        body = text[last_end : m.start()].strip()
        if body or last_head:
            parts.append((last_head, body))
        last_head, last_end = m.group(2).strip(), m.end()
    parts.append((last_head, text[last_end:].strip()))
    if fm:
        parts.insert(0, ("frontmatter", fm.strip()))
    return [(h, b) for h, b in parts if b]


def _split_by_headings(
    sections: list[tuple[str, str]], user_keys: tuple[str, ...], assistant_keys: tuple[str, ...]
) -> tuple[str, str]:
    u, a = [], []
    for h, b in sections:
        hl = h.lower()
        if any(k in hl for k in user_keys) or h in ("", "frontmatter"):
            u.append(f"## {h}\n{b}" if h and h != "frontmatter" else b)
        elif any(k in hl for k in assistant_keys):
            a.append(f"## {h}\n{b}" if h else b)
    return "\n\n".join(u).strip(), "\n\n".join(a).strip()


def _generic_split(sections: list[tuple[str, str]]) -> tuple[str, str]:
    """Fallback: first half of the sections is the ask, the rest is the answer."""
    body = [s for s in sections if s[0] != "frontmatter"]
    if len(body) < 2:
        return "", ""
    cut = max(1, len(body) // 2)
    u = "\n\n".join(f"## {h}\n{b}" if h else b for h, b in body[:cut])
    a = "\n\n".join(f"## {h}\n{b}" if h else b for h, b in body[cut:])
    return u.strip(), a.strip()


def _md_rows(
    paths: Iterable[Path],
    scrub: Scrubber,
    source: str,
    system: str,
    user_keys: tuple[str, ...],
    assistant_keys: tuple[str, ...],
    default_class: str,
    max_turn_chars: int,
    allow_generic: bool,
) -> Iterator[tuple[dict, bool]]:
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        secs = md_sections(text)
        u, a = _split_by_headings(secs, user_keys, assistant_keys)
        how = "headings"
        if (not u or not a) and allow_generic:
            u, a = _generic_split(secs)
            how = "generic"
        if not u or not a or len(a) < 40:
            continue
        rejected = bool(
            re.search(r"(?im)^(status|outcome|result)\s*:\s*(failed|rejected|abandoned)", text)
        )
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": scrub(_clip(u, max_turn_chars))},
            {"role": "assistant", "content": scrub(_clip(a, max_turn_chars))},
        ]
        cls = guess_class(u, msgs[-1])
        if cls == "draft":
            cls = default_class
        yield _row(msgs, cls, source, p, _date_of(p), {"split": how}), rejected


SYS_CARD = (
    "You are the Bot-OS executor. Given a work card (goal, definition of done, inputs), "
    "produce the receipt: what was done, evidence, and what remains. Be exact and brief."
)
SYS_ADR = (
    "You are the Bot-OS orchestrator. Given the context and options of a decision, "
    "state the decision and its consequences."
)
SYS_CASE = (
    "You are the ProWebCare malware-cleanup analyst. Given the evidence from a site, "
    "give the finding, the classification and the next step. Quote evidence verbatim."
)

CARD_USER = ("goal", "definition of done", "dod", "input", "scope", "context", "ask", "task", "why")
CARD_ASSISTANT = (
    "receipt",
    "result",
    "report",
    "done",
    "evidence",
    "outcome",
    "what was done",
    "retro",
    "lesson",
    "remaining",
    "next",
)
ADR_USER = ("context", "problem", "option", "alternative", "forces", "background")
ADR_ASSISTANT = ("decision", "consequence", "rationale", "chosen", "outcome", "status")
CASE_USER = (
    "evidence",
    "symptom",
    "report",
    "intake",
    "client said",
    "what we saw",
    "site",
    "environment",
    "timeline",
)
CASE_ASSISTANT = (
    "finding",
    "diagnosis",
    "classification",
    "family",
    "fix",
    "cleanup",
    "what we did",
    "lesson",
    "root cause",
    "verdict",
    "next",
)


# --------------------------------------------------------------------------- adapter: evalkit


def adapt_evalkit(
    paths: Iterable[Path], scrub: Scrubber, max_turn_chars: int
) -> Iterator[tuple[dict, bool]]:
    for p in paths:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        suite = p.parent.name.lower()
        for n, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            prompt = d.get("prompt") or d.get("input") or d.get("question") or d.get("instruction")
            gold = d.get("expected") or d.get("gold") or d.get("answer") or d.get("output")
            if not prompt or gold is None:
                continue
            if not isinstance(gold, str):
                gold = json.dumps(gold, ensure_ascii=False)
            if not isinstance(prompt, str):
                prompt = json.dumps(prompt, ensure_ascii=False)
            msgs = []
            if d.get("system"):
                msgs.append({"role": "system", "content": scrub(d["system"])})
            msgs += [
                {"role": "user", "content": scrub(_clip(prompt, max_turn_chars))},
                {"role": "assistant", "content": scrub(_clip(gold, max_turn_chars))},
            ]
            cls = d.get("class") or (
                "classify"
                if "classif" in suite
                else "extract"
                if "extract" in suite
                else "code"
                if "code" in suite
                else None
            )
            cls = cls if cls in CLASSES else guess_class(prompt, msgs[-1])
            yield _row(msgs, cls, "evalkit", p, _date_of(p), {"line": n, "suite": suite}), False


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--rejected", default=None, help="where rejected answers go (default: next to --out)"
    )
    ap.add_argument(
        "--deny-list",
        default=None,
        help="one client domain / word per line; replaced by [CLIENT_DOMAIN]",
    )
    ap.add_argument(
        "--drop-pattern",
        default=r"(?i)MEDICINA|medical|\.key[\\/]",
        help="regex; any source path matching it is never read",
    )
    ap.add_argument("--claude-code", nargs="*", default=[], metavar="DIR")
    ap.add_argument("--cards", nargs="*", default=[], metavar="DIR")
    ap.add_argument("--adr", nargs="*", default=[], metavar="DIR")
    ap.add_argument("--brain-cases", nargs="*", default=[], metavar="DIR")
    ap.add_argument("--evalkit", nargs="*", default=[], metavar="DIR")
    ap.add_argument(
        "--context-turns",
        type=int,
        default=6,
        help="claude_code: turns of context before the answer",
    )
    ap.add_argument("--max-turn-chars", type=int, default=8000)
    ap.add_argument("--max-tool-chars", type=int, default=2500)
    ap.add_argument("--min-answer-chars", type=int, default=20)
    ap.add_argument(
        "--no-tools", action="store_true", help="claude_code: drop tool_use turns (chatml only)"
    )
    ap.add_argument(
        "--keep-sidechain", action="store_true", help="claude_code: include subagent transcripts"
    )
    ap.add_argument(
        "--generic-split",
        action="store_true",
        help="markdown: when headings don't match, split the note in half (noisier)",
    )
    args = ap.parse_args(argv)

    drop = re.compile(args.drop_pattern) if args.drop_pattern else None
    scrub = Scrubber(load_deny_list(args.deny_list))
    out_p = Path(args.out)
    rej_p = (
        Path(args.rejected) if args.rejected else out_p.with_name(out_p.stem + ".rejected.jsonl")
    )
    out_p.parent.mkdir(parents=True, exist_ok=True)

    gens: list[Iterator[tuple[dict, bool]]] = []
    if args.claude_code:
        gens.append(
            adapt_claude_code(
                iter_files(args.claude_code, (".jsonl",), drop),
                scrub,
                context_turns=args.context_turns,
                max_turn_chars=args.max_turn_chars,
                max_tool_chars=args.max_tool_chars,
                include_tools=not args.no_tools,
                skip_sidechain=not args.keep_sidechain,
            )
        )
    if args.cards:
        gens.append(
            _md_rows(
                iter_files(args.cards, (".md",), drop),
                scrub,
                "cards",
                SYS_CARD,
                CARD_USER,
                CARD_ASSISTANT,
                "draft",
                args.max_turn_chars,
                args.generic_split,
            )
        )
    if args.adr:
        gens.append(
            _md_rows(
                iter_files(args.adr, (".md",), drop),
                scrub,
                "adr",
                SYS_ADR,
                ADR_USER,
                ADR_ASSISTANT,
                "draft",
                args.max_turn_chars,
                args.generic_split,
            )
        )
    if args.brain_cases:
        gens.append(
            _md_rows(
                iter_files(args.brain_cases, (".md",), drop),
                scrub,
                "brain_cases",
                SYS_CASE,
                CASE_USER,
                CASE_ASSISTANT,
                "classify",
                args.max_turn_chars,
                args.generic_split,
            )
        )
    if args.evalkit:
        gens.append(
            adapt_evalkit(iter_files(args.evalkit, (".jsonl",), drop), scrub, args.max_turn_chars)
        )
    if not gens:
        ap.error(
            "give at least one source (--claude-code / --cards / --adr / --brain-cases / --evalkit)"
        )

    seen: set[str] = set()
    counts: dict[str, int] = {}
    n_ok = n_rej = n_dup = n_short = 0
    with out_p.open("w", encoding="utf-8") as fo, rej_p.open("w", encoding="utf-8") as fr:
        for gen in gens:
            for row, rejected in gen:
                last = row["messages"][-1]
                if len(last.get("content") or "") < args.min_answer_chars and not last.get(
                    "tool_calls"
                ):
                    n_short += 1
                    continue
                if row["meta"]["sha"] in seen:
                    n_dup += 1
                    continue
                seen.add(row["meta"]["sha"])
                line = json.dumps(row, ensure_ascii=False) + "\n"
                if rejected:
                    fr.write(line)
                    n_rej += 1
                else:
                    fo.write(line)
                    n_ok += 1
                    key = f"{row['meta']['source']}/{row['meta']['class']}"
                    counts[key] = counts.get(key, 0) + 1

    print(f"wrote {n_ok} rows -> {out_p}")
    print(f"      {n_rej} rejected -> {rej_p}   (skipped: {n_dup} dup, {n_short} short)")
    for k in sorted(counts):
        print(f"  {k:28s} {counts[k]:6d}")
    if scrub.hits:
        print("scrubbed:", ", ".join(f"{k}={v}" for k, v in sorted(scrub.hits.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
