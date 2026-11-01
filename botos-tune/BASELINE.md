# Baseline — numbers to beat (Phase 0)

> Fill from `E:\Local-AI\botos-local-eval\results\<stamp>\report.html` after `run-all.cmd`.
> Status: **NOT RUN YET** (kit prepared 2026-10-28, see brain note "ASUS Ascent GX10 … Follow-up 3").

| class (eval-kit suite) | gemma4 first-try % | qwen3.6 first-try % | best other | notes |
|---|---|---|---|---|
| extract (brain-ingest step 2) | | | | JSON + verbatim quote, ≤2 evidence retries |
| classify (ADR-0013 L0–L6 ×18) | | | | |
| classify (failure taxonomy ×14) | | | | |
| code (7 Python tasks) | | | | hidden unit tests |
| prefix (skill pack cold vs warm) | | | | tok/s, 4k / 32k |

Speed (tok/s, 4k / 32k context): gemma4 ___ / ___ · qwen3.6 ___ / ___

**Gate for botos-v0.1 (Phase 3):** per in-scope class, first-try ≥ 90 % **and** ≥ baseline + 10 points.

Run stamp: `results\__________` · date: __________ · GPU clocks/driver: 610.88
