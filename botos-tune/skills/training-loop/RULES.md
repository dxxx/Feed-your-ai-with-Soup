# Training-loop rules (read before splitting any work)

One line per rule: `R<n> <date>: <cause> → <rule>`. Append only; mark a rule `SUPERSEDED by R<m>`
instead of deleting it.

- R1 2026-11-02: v0.1 saw ~18k tool-call answers with no tool list in the prompt and learned "always
  call a tool" → every tool-call row carries a `tools` list (tools it uses + core set); plain rows get
  `tools: []`; drop rows that call tools outside the catalog.
- R2 2026-11-02: first v0.1 scores loaded the adapter onto `Qwen3_5ForConditionalGeneration`
  (`language_model.*`) while Soup trained `AutoModelForCausalLM` (`model.layers.*`), so nothing
  attached and "tuned" = base → load with the same class Soup trained, and require
  `soup adapters check` exit 0 (non-zero lora_B) before any score counts.
- R3 2026-11-02: tool rows dominated the mix → cap the biggest class (tool ≤ 5,000, draft capped) and
  weight small classes up; check with `class-counts.py` before training.
- R4 2026-11-05: extract eval has n=10, so one task = 10 points and keep/revert is noise →
  `min_n ≥ 50` per gated class; below that the verdict is INCONCLUSIVE (= fail).
- R5 2026-11-05: a loop that only looks at one test set overfits it → keep a second locked final set,
  scored once, at the final step only.
- R6 2026-11-05: full runs take 6–12 h → every idea is tried as a fixed-budget proxy run first; only
  the winner gets a full run.
- R7 2026-11-02: a GitHub push with the private email was rejected → commit as
  `dxxx@users.noreply.github.com`.
