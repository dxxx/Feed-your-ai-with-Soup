# Bot-OS Knowledge Harvest Standard (KHS-1)

> Status: **v1.0 draft, 2026-11-02** · Owner: operator · Applies to every Bot-OS box.
> One rule above all: **work once, learn forever — but nothing leaves a box un-scrubbed.**

## 1. Why

Bot-OS runs on many boxes (dev centre, agency install, client copies, laptops, phone). Each one
produces knowledge: cards done, retros, decisions, logs, gotchas, vault facts, Claude transcripts.
Today only *gotchas* travel (the `bot-gotchas` sink). Everything else stays where it was made and
is lost when the box is wiped or the copy is replaced. This standard makes **every box emit one
harvest bundle, the same way, on a schedule**, so two consumers can read it:

1. **Work Brain** (the operator's memory): bundles are filed as notes.
2. **botos-tune** (the fine-tuning layer): bundles become training rows through `botos2jsonl.py`.

## 2. Scope

| term | meaning |
|---|---|
| **box** | one Bot-OS install on one machine, identified by a `site` id (same id as the gotcha sink: `s-0dc1` = ZENBOOK, …). A box is registered in `boxes.yaml` or it does not harvest. |
| **bundle** | one directory `harvest/<site>/<YYYY-MM-DD>T<HHMM>/` + its `.tar.gz`, produced by `harvest-box.py`. Self-describing: carries a `manifest.json` and a `SCRUB-REPORT.txt`. |
| **collector** | the box that pulls bundles in (RYZEN9 = canonical). Runs the ingest side. |
| **memory types** | episodic / semantic / procedural, exactly as CLAUDE.md §G defines them. |

Out of scope: live credentials, client evidence archives (zips, DB dumps, site backups), binaries,
anything under `.secrets/`, anything medical. These never enter a bundle, ever.

## 3. What a box harvests (per memory type)

| memory type | paths (relative to the Bot-OS root and each `projects/<name>/`) | harvested as | consumer |
|---|---|---|---|
| **episodic** | `done/`, `retros/`, `reports/`, `logs/*.md`, `decisions/`, `projects/*/done/`, `projects/*/reports/`, `projects/*/logs/*.md`, `projects/*/decisions/` | full markdown, append-only, never rewritten | both (cards → `cards`, ADRs → `adr` adapters) |
| **semantic** | `vault/hot.md`, `vault/KEY-FACTS.md`, `vault/entities/`, `vault/harvested-repos.tsv`, `projects/*/vault/` | full files; the collector diffs against the last bundle | Work Brain (facts), botos-tune only via `evalkit` gold rows |
| **procedural** | `agency/gotcha-outbox/` (or wherever `skill-gotcha.sh` writes), `retros/OS-LESSONS.md`, `skills/*/LESSONS.md`, `runbooks/` **changed since last bundle** | full files | skills fold (existing weekly harvest) + botos-tune `cards` adapter for LESSONS |
| **transcripts** | `~/.claude/projects/<this-box's project dirs>/*.jsonl`, `crew/<agent>/` | raw JSONL; scrubbed by the collector's `botos2jsonl.py` | botos-tune `claude_code` adapter; Work Brain chat importer |
| **telemetry** | `usage.sh` ledger, `heartbeat` receipts, `agency/task-classes.md` | copied as-is | the competence meter (which class is L0-eligible where) |

Rules:
- **Allow-list, never deny-list.** A path not in `boxes.yaml → harvest.include` is not read.
- `exclude` always wins: `.secrets/`, `*.key`, `*.pem`, `*.env`, `*.sql`, `*.zip`, `*.tar*`,
  `evidence/`, `backups/`, `node_modules/`, `.git/`, anything matching the collector's
  `--drop-pattern` (`MEDICINA|medical|\.key`).
- **Incremental by default:** a file goes in only if its mtime or sha changed since the box's last
  bundle (`harvest/<site>/.last-manifest.json`). `--full` overrides for a first run or a rebuild.
- Transcripts are harvested whole (the collector dedups rows by sha).

## 4. Bundle format

```
harvest/<site>/2026-11-02T2130/
  manifest.json          # see §4.1
  SCRUB-REPORT.txt       # counts per redaction pattern; the box operator reads this before shipping
  box.json               # the box's boxes.yaml entry at harvest time (tier, role, versions)
  episodic/   <relative paths preserved>
  semantic/
  procedural/
  transcripts/
  telemetry/
```
plus `harvest/<site>/2026-11-02T2130.tar.gz` (the shippable form) and the receipt line appended
to `harvest/<site>/HARVEST-LOG.tsv`.

### 4.1 `manifest.json`
```json
{"khs": 1, "site": "s-0dc1", "box": "ZENBOOK", "tier": "client-copy", "botos_version": "4.1.0",
 "created": "2026-11-02T21:30:00Z", "since": "2026-10-26T20:00:00Z", "full": false,
 "files": [{"path": "episodic/projects/os/done/2026-10-29-site-card.md", "sha256": "…", "bytes": 4120,
            "mtime": "2026-10-29T18:02:11Z", "type": "episodic"}],
 "counts": {"episodic": 12, "semantic": 3, "procedural": 1, "transcripts": 4, "telemetry": 2},
 "scrub": {"[EMAIL]": 7, "[IP]": 3, "[CLIENT_DOMAIN]": 41, "[REDACTED]": 1},
 "excluded": 18, "tool": "harvest-box.py 1.0"}
```
The manifest is the contract. A bundle without a valid manifest is refused by the collector.

### 4.2 De-identification (runs **on the box**, before the tarball exists)
Same scrubber as `botos2jsonl.py` (keys, tokens, `password=`, Bearer, emails → `[EMAIL]`,
IPv4 → `[IP]`, `P:\.key\…` paths, deny-listed client domains → `[CLIENT_DOMAIN]`) plus the box's
`.secrets/client-identity.map` (the existing sink mechanism) so client names map to stable
pseudonyms (`client-07`), not to `[CLIENT_DOMAIN]`, when the collector needs to keep cases apart.
`SCRUB-REPORT.txt` lists every pattern that fired and how often. **Zero hits is suspicious on a
client box** — check the allow-list before shipping.

## 5. Transport

| tier | how the bundle reaches the collector |
|---|---|
| canonical / agency install (same PC) | local copy to `E:\Local-AI\botos-harvest\inbox\<site>\` |
| laptops, client copies | the existing git sink: push `harvest/<site>/<stamp>.tar.gz` + `manifest.json` to `dxxx/bot-gotchas` under `harvest/<site>/` with the box's **write-only** deploy key (`.secrets/gotcha-sink.env`, `METHOD=git`) |
| phone (OnePlus Kali) / boxes without git | `scp` to the collector's inbox over the LAN; the Kali box has no deploy key |
| air-gapped | copy the `.tar.gz` by hand; the manifest's sha list is enough to verify |

Human-run, like `sync-gotchas.sh`: `harvest-box.py` (dry run, prints the manifest and the scrub
report) → `harvest-box.py --ship` (writes the tarball and appends the receipt). No box ships
automatically until its class is proven (3 clean manual runs), then it may go on a schedule.

## 6. Ingest on the collector

```
inbox/<site>/<stamp>.tar.gz
  → verify manifest (khs=1, site registered, every sha matches, no excluded pattern inside)
  → unpack to E:\Local-AI\botos-harvest\boxes\<site>\<stamp>\
  → Work Brain: one note "Harvest <site> <stamp>" in Inbox/Claude chats (counts, new cards, new
    decisions, lessons changed) — the tidy script files it
  → botos-tune: python tools\botos2jsonl.py --cards boxes\*\*\episodic --adr … --claude-code
    boxes\*\*\transcripts  (the collector runs the scrubber AGAIN; double scrub is cheap)
  → skills: existing harvest-gotchas.sh on procedural/
  → receipt appended to E:\Local-AI\botos-harvest\INGEST-LOG.tsv
```
A bundle that fails verification is moved to `quarantine/` with the reason; never partially used.

## 7. Cadence

| box tier | cadence | who runs it |
|---|---|---|
| canonical (RYZEN9) | daily, after the BrainTidy run | scheduled task (after 3 clean manual runs) |
| agency install | weekly (Sunday) | operator, with the gotcha harvest |
| client copies | end of every engagement + monthly | operator or the copy's heartbeat |
| laptops / phone | when back on the LAN | operator |

## 8. Gates (what makes a harvest "clean")

1. Manifest valid; every listed file present with matching sha.
2. `SCRUB-REPORT.txt` present; no raw email/IP/token survives a grep of the unpacked bundle.
3. No file from an `exclude` path inside the bundle.
4. Counts are plausible: a bundle with 0 episodic files from an active box is a warning, not a pass.
5. Receipt lines on both ends (`HARVEST-LOG.tsv` on the box, `INGEST-LOG.tsv` on the collector).

Three clean runs → the box's harvest class is **downgraded to script** (zero LLM tokens). A failed
gate escalates to the operator with the quarantine reason. Same ladder as everything else in Bot-OS.

## 9. Registry — `boxes.yaml`

Every box has an entry: `site`, `name`, `tier` (canonical | agency | client-copy | laptop |
phone | snapshot), `root`, `claude_projects` (its transcript dirs), `transport`, `cadence`,
`include` / `exclude` overrides, `status` (active | parked | retired). `harvest-box.py` refuses a
site that is not in the registry; `harvest-box.py --list` prints it.

## 10. What this standard does NOT change

- The gotcha pipeline (`skill-gotcha.sh` → `redact-for-sink.sh` → `sync-gotchas.sh` → weekly
  fold) keeps running as is; the bundle just carries the outbox too.
- Bot-OS upstream stays read-only; `harvest-box.py` lives in the fork's `botos-tune/tools/` and is
  copied into each box's `scripts/` by hand (or by the OS-update payload later).
- Write laws of CLAUDE.md §G: harvest **reads**; it never rewrites episodic files, never promotes
  semantic facts by itself.

## 11. Versioning

`khs` in the manifest is the schema version. Breaking changes bump it; the collector keeps one
reader per version. Changes to this document are logged below.

| date | change |
|---|---|
| 2026-11-02 | v1.0 draft: scope, memory-type table, bundle + manifest, scrub, transport, ingest, cadence, gates, registry. |
