# botos-tune — RESUME HERE

Kit for using this Soup fork as the fine-tuning layer under Bot-OS's local executor rung.
The plan is [`docs/botos-roadmap.md`](../docs/botos-roadmap.md); the Bot-OS card is
[`CARD.md`](CARD.md). This folder is copied to `E:\Local-AI\botos-tune\` by `install-soup.ps1`.

## State (2026-11-01)
- Phase 0 (eval-kit baseline): **not run** — operator runs `E:\Local-AI\botos-local-eval\run-all.cmd`, fills `BASELINE.md`.
- Phase 1 kit: **ready, tested in the cloud** on real Claude Code transcripts + markdown fixtures
  (`soup data validate` 100 % valid, leak check 0, ruff clean). Not yet run on the PC.
- Phase 2 config: `soup.yaml` validated against the Soup schema (v0.77.1).
- Waiting on the operator's three decisions (see `CARD.md`).

## Files
| file | what |
|---|---|
| `install-soup.ps1` | venv at `E:\Local-AI\soup`, `pip install soup-cli[train,mcp]`, copies this kit to `E:\Local-AI\botos-tune`, GPU sanity |
| `run-phase1.ps1` | converter → `soup data validate/clean/dedup --semantic/doctor/topics/split --stratify cls/canary insert` → class counts |
| `tools/botos2jsonl.py` | the converter: Claude Code transcripts, Bot-OS cards/retros, ADRs, Work Brain cases, eval-kit gold → chatml / tool-calling JSONL with `meta.class`; scrubs secrets, emails, IPs, deny-listed domains; rejected answers → `rejected.jsonl`; never reads paths matching `MEDICINA|medical|.key` |
| `tools/make-deny-list.py` | prints every client domain in the vault for `deny-list.txt` |
| `tools/class-counts.py` | rows per class/source; exit 2 if an in-scope class is under the bar (300) |
| `tools/make-eval-tasks.py` | held-out `test.jsonl` → `soup eval custom` task file (Phase 3) |
| `tools/test_botos2jsonl.py` | pytest for the converter (`python -m pytest botos-tune/tools -q -o addopts=''`) |
| `skills/training-loop/` | **permanent skill**: Karpathy keep/revert loop for every training run — `SKILL.md`, learned `RULES.md`, `gate.template.json`, `loop-check.py` (gate as code: exit 0 KEEP / 2 REVERT / 1 check broken, ledger `attempts.tsv`). Install: `skills\install-skills.ps1 [-BotOS <test copy>]` |
| `HARVEST-STANDARD.md` | **KHS-1**: how every Bot-OS box emits one scrubbed harvest bundle (episodic / semantic / procedural / transcripts / telemetry) for Work Brain + botos-tune |
| `boxes.yaml` | registry of all Bot-OS boxes (site id, tier, root, transcript dirs, transport, cadence) — a box not listed does not harvest |
| `tools/harvest-box.py` | runs on a box: allow-list collect → scrub → `manifest.json` + `SCRUB-REPORT.txt` → `.tar.gz` + receipt; incremental; `--verify` on the collector |
| `tools/test_harvest_box.py` | pytest for the harvester (registry parser, ship/incremental, leak check, verify, tamper) |
| `deny-list.txt` | seed deny-list (operator decision #2) |
| `soup.yaml` | Phase 2 training config, QLoRA Qwen2.5-7B-Instruct |
| `BASELINE.md` | Phase 0 table to fill |
| `evals/` | Phase 3 notes + task-file example |

## Order of operations on the PC
```powershell
powershell -ExecutionPolicy Bypass -File install-soup.ps1          # once
E:\Local-AI\soup\.venv\Scripts\Activate.ps1 ; cd E:\Local-AI\botos-tune
python tools\make-deny-list.py "E:\BRAINS-MEMMORIES\WORK_BRAIN" >> deny-list.txt   # review it
.\run-phase1.ps1                                                     # dataset
soup advise data\train.jsonl --goal "answer Bot-OS extract/classify tasks as JSON, first try" --probe
soup train --config soup.yaml --find-lr ; # set training.lr ; soup train --config soup.yaml --tensorboard
```
Then Phase 3 in the roadmap. `data\canary.json` is a secret: never commit it.

## Never
Push to `dxxx/Bot-OS`; train on the medical vault; put `P:\.key` contents anywhere near `data\`.
