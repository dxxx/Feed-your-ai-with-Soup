---
name: training-loop
description: Karpathy-style keep/revert loop for fine-tuning a local model with Soup — one change per attempt, a fixed programmatic gate, short proxy runs before full runs, max 3 attempts per idea, every attempt logged, lessons written to RULES.md. Use whenever the user wants to train, retrain, tune, improve or re-score a model (botos-vX.Y, any Soup run), or asks "why did the model fail / what do we change next".
---

# Training loop (Karpathy loop for model training)

Built on karpathy/autoresearch: change one thing, run a fixed-budget experiment, measure one fixed
check, keep or revert, log it. Adapted for Soup runs that take hours, not minutes.

**Read `RULES.md` in this folder before splitting any work, and apply every rule to every unit.**

## 0. Ground rules
- The operator approves only the final step (deploy / promote). Everything before it is verified
  by a program, not by the operator and not by "looks good".
- **Never edit the gate during a loop.** The gate file is frozen at loop start (sha recorded in the
  ledger). Changing it starts a new loop.
- One GPU = training units run one at a time. Data and eval units may run in parallel.
- Bot-OS rules still apply: local model stays at action levels L0–L1; no secrets or medical data in
  any dataset; Bot-OS upstream is read-only.

## 1. Check first — write the gate before any work
Copy `gate.template.json` to the run folder as `gate.json` and fill it. A gate is only valid if
`loop-check.py` can evaluate it. It always contains:

| check | source | pass |
|---|---|---|
| per-class score | eval-kit `*.summary.json` (base and candidate, same serve path) | `>= min` **and** `>= base + min_delta` |
| sample size | `n` in the same summary | `>= min_n` (smaller = INCONCLUSIVE = fail) |
| adapter attached | `soup adapters check <adapter>` exit code | 0 (`alive`) |
| task-win, no regression | `soup ship` exit code | 0 (SHIP) |
| canary not memorised | `soup data canary check` exit code | 0 |
| behaviour | `soup diagnose --output d.json` | no `MAJOR` |

Two test sets, both locked before training: **loop set** (the loop may look at it after every
attempt) and **final set** (scored once, only for the final step — it guards against the loop
overfitting the loop set).

## 2. Split into units
Each unit: one job, one input, one output, one named failure state. Edge only when a unit reads
another unit's output.

```
 [convert:source A] [convert:source B] ... (parallel)   fail: validate < 100 % / leak > 0
            \            |            /
             [merge + dedup + scrub]                    fail: leak grep > 0
                        |
             [balance + split + canary]                 fail: class-counts exit 2
                        |
             [proxy-train: ONE change]                  fail: loss NaN / adapter inactive
                        |
             [score loop set: base + cand]  (parallel)  fail: loop-check exit 2
                        |
             [full-train winner] -> [score final set] -> [operator approves deploy]
```

## 3. Run — produce, check, fix (max 3 attempts per unit)
1. **Proxy run first.** Fixed budget per attempt (default: `max_steps: 60` on a 500-row stratified
   subset + loop-set eval, ~20–30 min on the RTX 5080). Only the winning change gets a full run.
2. Change exactly **one** thing per attempt (a data rule, lr, rank, epochs, base model, template).
3. Score base and candidate through the **same** serve path (same quantisation, same chat
   template, thinking off). Then:
   ```
   python loop-check.py --gate gate.json --base base.summary.json --cand cand.summary.json \
       --adapter-check-rc $A --ship-rc $S --canary-rc $C --diagnose d.json \
       --ledger attempts.tsv --unit proxy-train --attempt 2 --change "tools list on every tool row"
   ```
   exit 0 = keep · exit 2 = revert · exit 1 = the check itself is broken (fix the check, not the model).
4. Revert = delete the candidate adapter dir and restore the previous data/config from git. The
   ledger line stays.
5. **3 failed attempts on the same unit → stop.** Report that the plan is wrong. Do not try a 4th.

## 4. Merge with code
Score comparison, dedup, class counts, leak checks: scripts only (`loop-check.py`,
`class-counts.py`, `soup data validate`, `grep`). Model reasoning is spent only on *why* an attempt
failed and *what single change* to try next — read the raw answers in `results/*/raw/` for that.

## 5. Return only the failed unit
```
UNIT:     proxy-train
VERDICT:  FAIL (extract 0.40 < 0.90; delta -0.40 < +0.10)
REASON:   plain-JSON task answered with a Bash tool call
EVIDENCE: results/B/botos-v0.1/raw/extract-05.json
SCOPE:    runs/botos-v0.2/prep.py only
```
Never redo units that already passed.

## 6. Gate by cost to undo
| change | class | action |
|---|---|---|
| new dataset file, proxy/full training, scoring, adapter on disk | cheap, contained | do it |
| merge → GGUF → Ollama model, listing it in `runbooks/local-executor.md` | reversible, wide | only on a PASS of the final set + 3 clean production runs |
| deleting data/runs, creating users or keys on servers, pushing upstream, spending money (cloud GPU) | irreversible | **stop and ask**, whatever the score |

## 7. Learn
When a fix passes, add one line to `RULES.md` (`- R<n> <date>: <cause> → <rule>`), and apply it to
every unit split after that. A rule that keeps firing becomes a check inside `loop-check.py` or the
data builder.

## Stop
Stop when the gate passes on the final set, or after 2 rounds with nothing new, or when the GPU
budget in `gate.json` is spent. Then report once:
- **Changed:** the kept change(s), one line each
- **Checked:** the `loop-check.py` table (per class: base, candidate, delta, verdict)
- **Ledger:** `attempts.tsv` (all attempts, including rejected)
- **Needs approval:** the deploy step and anything irreversible

## Files
- `RULES.md` — learned rules (read first)
- `gate.template.json` — gate to copy per run
- `loop-check.py` — the gate as code (stdlib only); `test_loop_check.py` its tests
