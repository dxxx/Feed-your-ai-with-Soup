# Phase 3 — evaluate and gate

```powershell
python tools\make-eval-tasks.py data\test.jsonl -o evals\botos-tasks.jsonl       # from the held-out split
soup eval custom --model .\runs\botos-v0.1 --tasks evals\botos-tasks.jsonl         # tuned
soup eval custom --model Qwen/Qwen2.5-7B-Instruct --tasks evals\botos-tasks.jsonl  # base, same tasks
soup ship --base Qwen/Qwen2.5-7B-Instruct --adapter .\runs\botos-v0.1 --task-eval evals\botos-tasks.jsonl
soup diagnose <run-id>
soup data canary check --manifest data\canary.json --base .\runs\botos-v0.1        # exit 2 = memorised
soup eval design data\test.jsonl --goal "..." -o evals\design.json ; soup eval lock evals\design.json -o evals\lock.json
```
Then the existing kit on the exported model: `run-all.cmd -Models botos-v0.1 -NoDownload`
(needs Phase 4.1 export first).

Gate per class: eval-kit first-try ≥ 90 % **and** ≥ baseline + 10 · `soup ship` = SHIP · `soup diagnose` no MAJOR · canary exit 0.

`botos-tasks.example.jsonl` shows the task-file shape (`scoring`: `answer` | `contains` | `regex`).
