# Bot-OS × Soup — implementation roadmap

> Owner: Dumitru Butucel · Started 2026-11-01 · Status: **Phase 0 (baseline), nothing run yet**
>
> Goal: use Soup to turn Bot-OS's completed work into a local model that handles the proven,
> bounded task classes (extract, classify, reformat, first drafts) on the RTX 5080, so Bot-OS
> pays Claude only for judgment. Bot-OS law applies: *unknown work goes up, proven work goes
> down, verified work gets cheaper.* A fine-tune is just the next rung below "L0 Ollama rung".

## Ground rules (do not break)

1. **Bot-OS upstream (`dxxx/Bot-OS`) is read-only.** Everything here lives in the Desktop test
   copy `C:\Users\dXXX\Desktop\Bot-OS\Bot-OS`: commit locally, never push.
2. **Nothing replaces the executor contract.** The fine-tuned model is just another `--model`
   behind `scripts/ollama-run.sh` / `llamacpp-run.sh` (same flags, same exit codes 0/1/2/3/4).
   The caller's mandatory check (shape / ground truth / spot check) stays.
3. **No live actions from the local model.** It stays at action levels L0–L1 (read-only, local
   draft). Nothing it emits is executed without the normal gate.
4. **Data hygiene.** Training data is scrubbed of credentials, client PII and medical content
   before it leaves the build folder. Secrets live in `P:\.key` and are never in a JSONL.
5. **Every rung is earned.** A task class moves to the fine-tuned model only after
   ≥90% first-try pass on its eval and 3 clean production runs (same bar as the L0 rung).

## Where things live

| what | path |
|---|---|
| this fork of Soup | `dxxx/feed-your-ai-with-soup` (branch `ccr-768bd8fd-y0v6ms`) |
| Soup install on RYZEN9 | `E:\Local-AI\soup\` (venv, Python 3.13.7 — use `python`, not the Store `python3` stub) |
| build folder (datasets, configs, runs) | `E:\Local-AI\botos-tune\` |
| models | `E:\Local-AI\models\` (shared with the eval kit) |
| local-model eval kit (baseline) | `E:\Local-AI\botos-local-eval\` |
| Bot-OS episodic memory (source) | test copy `logs/ reports/ done/ retros/ decisions/` + agency install `E:\Malware-Cleanup-Services\Bot-OS\projects\*\` |
| Work Brain (source) | `E:\BRAINS-MEMMORIES\WORK_BRAIN` (`Cases/`, `Knowledge/`, `Lessons`, `Chats/`) |
| Claude Code transcripts (source) | `~\.claude\projects\*\*.jsonl` |
| ports | `port get botos-tune <purpose>` — never pick one by hand |

## Hardware budget

RTX 5080 16 GB + 64 GB RAM. Fits comfortably: QLoRA (4-bit) on 7–14B. Candidate bases, in
order: **Qwen2.5-7B-Instruct** (tool-calling native, Apache-2.0), Qwen2.5-14B-Instruct,
gemma-3-12b-it (the current L0 rung's family — only if the eval says gemma4 is the better
baseline). Check fit before every new base: `soup profile --model <id> --gpu rtx5080 --method qlora`.

---

## Phase 0 — Baseline (prerequisite, already prepared)

**Why:** without the baseline there is nothing to beat, and `soup advise` may say "don't train".

- [ ] Close GPU apps (Hemmingway :8099), run `E:\Local-AI\botos-local-eval\run-all.cmd`
      (`-Quick` ≈10 min/model). Read `results\<stamp>\report.html`.
- [ ] Record per task class (extract / classify / code / prefix) the first-try pass rate for
      gemma4 and qwen3.6. These become **the numbers to beat** in Phase 3.
- [ ] Decide the GX10 question from the report's "GX10 vs this PC" line (separate decision).

**Exit:** a table `class → baseline pass % → best local model` in `E:\Local-AI\botos-tune\BASELINE.md`.

---

## Phase 1 — Install Soup + first dataset (1–2 evenings)

### 1.1 Install
```powershell
cd E:\Local-AI\soup
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install "soup-cli[train,mcp]"        # PyPI release; or pip install -e . from this fork
soup --version ; soup profile --model Qwen/Qwen2.5-7B-Instruct --gpu rtx5080 --method qlora
```
Windows notes: bitsandbytes 4-bit works on Windows wheels ≥0.43; if it fails, fall back to
`quantization: none` + `lora.r: 16` on the 7B (fits in 16 GB in bf16 with gradient checkpointing),
or run training under WSL2 (CUDA passes through).

### 1.2 Converter: Bot-OS memory → chatml JSONL (the one piece Soup lacks)
Script `E:\Local-AI\botos-tune\tools\botos2jsonl.py` (Python 3.13, stdlib only). One source
adapter per memory type, each emitting `{"messages":[system,user,assistant], "meta":{...}}`:

| source | adapter | user turn | assistant turn |
|---|---|---|---|
| Claude Code transcripts `*.jsonl` | `claude_code` | the user prompt + tool results up to the assistant turn | the assistant text (and `tool_calls` where present → `tools` list from the MCP schemas) |
| Bot-OS `done/` + `retros/` cards | `cards` | the card's goal + DoD + inputs | the receipt / final report section |
| `decisions/` ADRs | `adr` | context + options | decision + consequences |
| Work Brain `Cases/` + `Knowledge/Malware cleanup/` | `brain_cases` | the evidence block | the finding / classification / next step |
| eval-kit extract/classify fixtures (gold) | `evalkit` | the kit's prompt | the gold JSON answer |

Rules the converter enforces:
- `meta.class` = one of the Bot-OS task classes (`extract`, `classify`, `reformat`, `draft`,
  `code`, `tool`) — this is what Phase 3 evaluates per class.
- `meta.source`, `meta.date`, `meta.sha` for lineage; `meta.risk` ≤ L1 only.
- Scrub pass before write: regexes for keys/tokens/passwords, emails, IPs of client servers,
  and a deny-list of client domains that must not be in training data. **Medical vault is
  never a source.**
- Skip assistant turns that were later marked wrong (retro says `failed`, thumbs-down, or a
  later turn corrects it) — those go to a separate `rejected.jsonl` for Phase 4 (DPO).

### 1.3 Clean + split with Soup
```bash
soup data validate data/raw.jsonl
soup data clean data/raw.jsonl -o data/clean.jsonl
soup data dedup data/clean.jsonl --semantic --threshold 0.85 -o data/dedup.jsonl
soup data doctor data/dedup.jsonl --model Qwen/Qwen2.5-7B-Instruct      # chat-template compat
soup data topics data/dedup.jsonl --clusters auto                         # thin-class warning
soup data split data/dedup.jsonl --val 10 --test 10 --stratify class      # by meta.class
soup data canary insert data/train.jsonl -o data/train.canary.jsonl --manifest data/canary.json
```
Target size: **≥300 rows per class** for extract/classify, ≥1,000 total. If a class is thin,
`soup data generate --provider ollama --template qa` from the skill/runbook text, then
`soup data filter --coherence 0.3`. Generated rows get `meta.source: synthetic`.

**Exit:** `train/val/test.jsonl` + `BASELINE.md` + the converter under local git in the test copy.

---

## Phase 2 — Decide + first training run (1 evening + GPU time)

### 2.1 Pre-flight
```bash
soup advise data/train.jsonl --goal "answer Bot-OS extract/classify tasks as JSON, first try, same as the skill pack" --probe
```
- Verdict **PROMPT_ENG / RAG** → stop here; the win is a better prompt cache / skill pack, not
  weights. Record it and close the phase.
- Verdict **SFT** → continue. Save `soup advise explain` output to the run folder.

### 2.2 Config `E:\Local-AI\botos-tune\soup.yaml`
```yaml
base: Qwen/Qwen2.5-7B-Instruct
task: sft
data:
  train: ./data/train.canary.jsonl
  val: ./data/val.jsonl
  format: chatml            # tool rows auto-detect as tool-calling via the `tools` key
  max_length: 4096
training:
  epochs: 2
  lr: 1e-4
  batch_size: auto
  eval_steps: 50
  seed: 42
  quantization: 4bit
  lora: { r: 32, alpha: 64, target_modules: auto }
output: ./runs/botos-v0.1
```

### 2.3 Train
```bash
soup train --config soup.yaml --find-lr        # once, take the recommended LR
soup train --config soup.yaml --tensorboard
soup adapters check ./runs/botos-v0.1          # must end "alive"
soup adapters audit ./runs/botos-v0.1 --config soup.yaml
soup registry push --run-id <id> --name botos --tag v0.1 --data data/train.canary.jsonl
```

**Exit:** a registered adapter with loss curves that are not flat and not collapsed.

---

## Phase 3 — Evaluate and gate (the only step that decides anything)

Build the eval once, lock it, reuse forever.

```bash
soup eval design data/test.jsonl --goal "..."  -o evals/design.json
soup eval lock evals/design.json -o evals/lock.json           # checksummed suite
soup eval custom --model ./runs/botos-v0.1 --tasks data/test.jsonl   # per-class accuracy
soup ship --base Qwen/Qwen2.5-7B-Instruct --adapter ./runs/botos-v0.1 --task-eval data/test.jsonl
soup diagnose <run-id>                                         # forgetting / format / mode collapse
soup data canary check --manifest data/canary.json --base ./runs/botos-v0.1   # exit 2 = memorised
```

Also run the **existing eval kit** against the tuned model (it already has an llama-server /
Ollama path): export first (Phase 4.1), then `run-all.cmd -Models botos-v0.1 -NoDownload`.

Gate per task class (same bar as the Ollama rung):
| check | pass |
|---|---|
| first-try pass on eval kit class | ≥90% **and** ≥ baseline + 10 points |
| `soup ship` | SHIP (exit 0) |
| `soup diagnose` | no MAJOR on refusal / format / forgetting |
| canary check | exit 0 |

Classes that pass → "fine-tune-eligible" in their skill/runbook. Classes that fail → stay on
the existing ladder; log why in `retros/`.

---

## Phase 4 — Deploy behind the existing executor contract

```bash
soup merge --adapter ./runs/botos-v0.1 --low-memory -o ./runs/botos-v0.1-merged
soup export --model ./runs/botos-v0.1-merged --format gguf --deploy ollama   # name: botos-v0.1
soup deploy ollama --list
```
- `ollama-run.sh --model botos-v0.1 ...` and `llamacpp-run.sh` work unchanged; add
  `botos-v0.1` to the model allow-list in `runbooks/local-executor.md`.
- Q4_K_M quant for Ollama; re-run `soup eval quant-check --before merged --after gguf` and
  accept only OK/MINOR.
- 3-clean-runs certification on real cards before FOLD marks the class "downgraded".

**Exit:** `runbooks/local-executor.md` lists the tuned model and its certified classes.

---

## Phase 5 — Make it learn forever (flywheel)

Optional once v0.1 serves at least one class. All local, all gated.

1. **Thumbs as training signal.** For the review step, serve the model through Soup instead of
   raw Ollama so every verified/rejected answer is captured:
   `soup serve --model ./runs/botos-v0.1-merged --record-thumbs ./rl.db --port $(port get botos-tune serve)`.
   The executor's mandatory check posts 👍/👎 to `POST /v1/thumbs`.
2. **Preference pairs** from Bot-OS's own retros: `rejected.jsonl` (Phase 1.2) + thumbs →
   `soup data lint prefs.jsonl` → DPO run (`task: dpo`), gated the same way as Phase 3.
3. **Automated loop:** `soup loop init registry://botos-v0.1 --eval evals/lock.json --baseline registry://prod --pre-wired --thumbs-db ./rl.db --max-runs-per-day 1`
   and `soup loop watch` as a scheduled task; canary via `soup loop canary --traffic 5%`,
   auto-rollback on MAJOR.
4. **Tool-calling rung.** `soup agent synth --spec <work-brain-mcp.json> -o ds.jsonl` builds
   calls against Work Brain / ChromeMCP schemas; `soup agent eval --sandbox` scores them. Adds
   the `tool` class only after it passes the same gate.
5. **Rehearsal when retraining:** `soup train --replay data/train.v0.1.jsonl --replay-ratio 0.1`
   so v0.2 does not forget v0.1's classes.

---

## Phase 6 — Soup as a Bot-OS tool (optional, after Phase 4)

`soup mcp serve` (stdio, plan-only by default) in `.claude/settings.json` of the test copy, so
the orchestrator can ask "does this fit / what would the run be" without executing. Never
`--allow-execute` from an agent session; training is an operator-launched job.

---

## Decisions already taken

| date | decision |
|---|---|
| 2026-11-01 | Soup is the fine-tuning layer; it does not replace Ollama/llama.cpp as the runtime. |
| 2026-11-01 | First base = Qwen2.5-7B-Instruct QLoRA, on-PC; no cloud GPU for v0.1. |
| 2026-11-01 | Phase 0 (eval kit baseline) runs before any training. |
| 2026-11-01 | Classes in scope for v0.1: `extract`, `classify`. `draft`/`code`/`tool` later. |

## Open decisions for the operator

- [ ] Which Claude Code project folders count as training sources (all, or only Bot-OS + ProWebCare)?
- [ ] Client domain deny-list for the scrubber — provide or approve the default (all `Clients/` domains).
- [ ] Training on-PC at night vs. a one-off cloud run (`soup train --cloud runpod --gpu a100`) if a 14B is wanted.

## Progress log

| date | phase | result |
|---|---|---|
| 2026-11-01 | — | Roadmap written. Eval kit still not run. |
