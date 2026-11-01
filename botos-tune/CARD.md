---
id: 2026-11-01-soup-finetune-layer
title: Soup as the fine-tuning layer under the L0 local rung
status: in-progress
priority: P2
risk: L2
owner: operator
created: 2026-11-01
project: Bot-OS
lane: dev
depends_on: botos-local-eval baseline (E:\Local-AI\botos-local-eval, prepared 2026-10-28, not run)
roadmap: docs/botos-roadmap.md in dxxx/feed-your-ai-with-soup (branch ccr-768bd8fd-y0v6ms)
---

# Card: Soup as the fine-tuning layer under the L0 local rung

Copy this file to `projects/os/in-progress/2026-11-01-soup-finetune-layer.md` in the **Desktop
test copy** (`C:\Users\dXXX\Desktop\Bot-OS\Bot-OS`). Commit locally. Never push upstream.

## Goal
Turn completed Bot-OS work (cards, retros, ADRs, Work Brain cases, Claude Code transcripts) into
a QLoRA fine-tune of Qwen2.5-7B-Instruct that handles the proven `extract` and `classify` task
classes on the RTX 5080, deployed behind the unchanged `ollama-run.sh` / `llamacpp-run.sh`
executor contract. "Work once, learn forever", in the weights.

## Definition of done
1. `BASELINE.md` filled from the eval kit (Phase 0).
2. `data/train|val|test.jsonl` built by `run-phase1.ps1`, ≥300 rows per in-scope class, scrub
   report clean, `soup data doctor` OK (Phase 1).
3. `soup advise` verdict recorded; if SFT, adapter `botos-v0.1` trained, `adapters check` =
   alive, registered (Phase 2).
4. Gate passed per class: eval-kit first-try ≥90% and ≥ baseline+10, `soup ship` = SHIP,
   `soup diagnose` no MAJOR, canary check exit 0 (Phase 3).
5. GGUF in Ollama as `botos-v0.1`, listed in `runbooks/local-executor.md` with its certified
   classes, 3 clean production runs → FOLD (Phase 4).

## Out of scope (this card)
`draft` / `code` / `tool` classes; DPO flywheel (`soup loop`); cloud GPU; any change to the
canonical Bot-OS repo; any live (L3+) action by the local model.

## Inputs
- Kit: `botos-tune/` in the fork (converter, scrubber, deny-list, `soup.yaml`, install + run
  scripts, eval task template). Converter tested on real transcripts: `soup data validate` 100%
  valid, fixture leak check 0.
- Eval kit: `E:\Local-AI\botos-local-eval\` (`run-all.cmd`).
- Roadmap: `docs/botos-roadmap.md`.

## Gates / checks
- Scrub report printed by the converter (secrets, emails, IPs, deny-listed domains).
- `data/canary.json` is a SECRET: never committed, never shown to the model.
- Every answer from `botos-v0.1` still gets the caller's mandatory shape / ground-truth / spot
  check; at most 2 retries at the same tier, then escalate (runbooks/local-executor.md).

## Open decisions (operator)
- [ ] #1 Training sources: all Claude Code project folders, or Bot-OS + ProWebCare only?
- [ ] #2 Deny-list: approve default (all `Clients/` domains via `make-deny-list.py`) or supply.
- [ ] #3 On-PC nightly 7B only, or allow one cloud run if a 14B is needed?

## Log
| date | what |
|---|---|
| 2026-11-01 | Roadmap + kit written and pushed to the fork. Eval kit still not run. |

## Receipt
_(empty until done)_
