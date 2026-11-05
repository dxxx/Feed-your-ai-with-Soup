#!/usr/bin/env python
"""loop-check.py - the training-loop gate as code (see SKILL.md). Stdlib only.

    python loop-check.py --gate gate.json --base base.summary.json --cand cand.summary.json
        [--adapter-check-rc N] [--ship-rc N] [--canary-rc N] [--diagnose d.json]
        [--ledger attempts.tsv --unit NAME --attempt N --change "one line"]

Exit codes: 0 = KEEP (every check passed) · 2 = REVERT (a check failed or was inconclusive)
            1 = the check itself is broken (bad gate, missing file, missing key).

A required return code that was not supplied counts as a failure: nothing passes by omission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


class CheckError(Exception):
    """The check could not be evaluated (exit 1)."""


def dig(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise CheckError(f"missing key {dotted!r}")
        cur = cur[part]
    return cur


def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise CheckError(f"file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise CheckError(f"not JSON: {path}: {e}") from e


def _diagnose_has(report, words: list[str]) -> list[str]:
    """Return every forbidden word found anywhere in a diagnose report (verdict strings)."""
    found: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for w in words:
                if x.strip().upper() == w.upper():
                    found.append(w)

    walk(report)
    return found


def evaluate(gate: dict, base: dict, cand: dict, rcs: dict[str, int | None],
             diagnose: dict | None) -> list[dict]:
    rows: list[dict] = []
    classes = gate.get("classes") or {}
    if not classes:
        raise CheckError("gate has no classes")
    for name, spec in classes.items():
        try:
            b = float(dig(base, spec["path"]))
            c = float(dig(cand, spec["path"]))
            n = int(dig(cand, spec["n_path"])) if spec.get("n_path") else None
        except KeyError as e:
            raise CheckError(f"gate class {name!r} lacks {e}") from e
        mn, md, mnn = spec.get("min", 0.0), spec.get("min_delta", 0.0), spec.get("min_n", 0)
        delta = c - b
        if n is not None and n < mnn:
            verdict, why = "INCONCLUSIVE", f"n={n} < min_n={mnn}"
        elif c < mn:
            verdict, why = "FAIL", f"{c:.3f} < min {mn:.2f}"
        elif delta < md - 1e-9:
            verdict, why = "FAIL", f"delta {delta:+.3f} < +{md:.2f}"
        else:
            verdict, why = "PASS", ""
        rows.append({"check": name, "base": b, "cand": c, "delta": delta, "n": n,
                     "verdict": verdict, "why": why})
    for key, want in (gate.get("required_rc") or {}).items():
        got = rcs.get(key)
        if got is None:
            rows.append({"check": key, "verdict": "FAIL", "why": "not supplied"})
        elif got != want:
            rows.append({"check": key, "verdict": "FAIL", "why": f"rc {got} != {want}"})
        else:
            rows.append({"check": key, "verdict": "PASS", "why": ""})
    forbid = gate.get("diagnose_forbid") or []
    if forbid:
        if diagnose is None:
            rows.append({"check": "diagnose", "verdict": "FAIL", "why": "not supplied"})
        else:
            hits = _diagnose_has(diagnose, forbid)
            rows.append({"check": "diagnose", "verdict": "FAIL" if hits else "PASS",
                         "why": f"found {sorted(set(hits))}" if hits else ""})
    return rows


def render(rows: list[dict]) -> str:
    out = [f"{'check':16s} {'base':>6s} {'cand':>6s} {'delta':>7s} {'n':>4s}  verdict"]
    for r in rows:
        if "base" in r:
            n = "" if r["n"] is None else str(r["n"])
            out.append(f"{r['check']:16s} {r['base']:6.3f} {r['cand']:6.3f} {r['delta']:+7.3f} "
                       f"{n:>4s}  {r['verdict']} {r['why']}".rstrip())
        else:
            pad = " " * 28
            out.append(f"{r['check']:16s}{pad}  {r['verdict']} {r['why']}".rstrip())
    return "\n".join(out)


def append_ledger(path: str, gate_path: str, unit: str, attempt: int, change: str,
                  keep: bool, rows: list[dict]) -> None:
    p = Path(path)
    new = not p.exists()
    gate_sha = hashlib.sha256(Path(gate_path).read_bytes()).hexdigest()[:12]
    failed = "; ".join(f"{r['check']}:{r['verdict']}" for r in rows if r["verdict"] != "PASS")
    with p.open("a", encoding="utf-8") as fh:
        if new:
            fh.write("time\tunit\tattempt\tchange\tdecision\tgate_sha\tfailed\n")
        fh.write("\t".join([datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), unit,
                            str(attempt), change.replace("\t", " "),
                            "KEEP" if keep else "REVERT", gate_sha, failed or "-"]) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--cand", required=True)
    ap.add_argument("--adapter-check-rc", type=int)
    ap.add_argument("--ship-rc", type=int)
    ap.add_argument("--canary-rc", type=int)
    ap.add_argument("--diagnose")
    ap.add_argument("--ledger")
    ap.add_argument("--unit", default="unit")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--change", default="")
    ap.add_argument("--json", action="store_true", help="print rows as JSON too")
    a = ap.parse_args(argv)
    try:
        gate = _load(a.gate)
        rows = evaluate(gate, _load(a.base), _load(a.cand),
                        {"adapter_check": a.adapter_check_rc, "ship": a.ship_rc,
                         "canary": a.canary_rc},
                        _load(a.diagnose) if a.diagnose else None)
    except CheckError as e:
        print(f"CHECK BROKEN: {e}", file=sys.stderr)
        return 1
    keep = all(r["verdict"] == "PASS" for r in rows)
    print(render(rows))
    print("DECISION:", "KEEP" if keep else "REVERT")
    max_att = (gate.get("budget") or {}).get("max_attempts_per_unit", 3)
    if not keep and a.attempt >= max_att:
        print(f"STOP: {a.unit} failed {a.attempt}/{max_att} attempts - the plan is wrong, "
              "do not retry")
    if a.json:
        print(json.dumps(rows))
    if a.ledger:
        append_ledger(a.ledger, a.gate, a.unit, a.attempt, a.change, keep, rows)
    return 0 if keep else 2


if __name__ == "__main__":
    sys.exit(main())
