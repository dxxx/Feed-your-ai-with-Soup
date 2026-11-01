# Bot-OS × Soup — Phase 1.2 + 1.3: build the dataset (docs/botos-roadmap.md)
# Run from E:\Local-AI\botos-tune with the Soup venv active.
#   .\run-phase1.ps1                 # full build
#   .\run-phase1.ps1 -SkipConvert    # re-run only the Soup data steps on data\raw.jsonl
param(
    [switch]$SkipConvert,
    [string]$BotOS = "$env:USERPROFILE\Desktop\Bot-OS\Bot-OS",     # local TEST copy, never upstream
    [string]$Agency = "E:\Malware-Cleanup-Services\Bot-OS",
    [string]$Brain = "E:\BRAINS-MEMMORIES\WORK_BRAIN",
    [string]$ClaudeProjects = "$env:USERPROFILE\.claude\projects",
    [string]$EvalKit = "E:\Local-AI\botos-local-eval\suites",
    [string]$Model = "Qwen/Qwen2.5-7B-Instruct"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path data | Out-Null

if (-not $SkipConvert) {
    Write-Host "== 1.2 convert sources -> data\raw.jsonl"
    # Open decision #1 in the roadmap: which Claude Code project folders count. Default = all;
    # narrow with e.g. --claude-code "$ClaudeProjects\C--Users-dXXX-Desktop-Bot-OS-Bot-OS".
    python tools\botos2jsonl.py --out data\raw.jsonl --rejected data\rejected.jsonl `
        --deny-list deny-list.txt `
        --claude-code $ClaudeProjects `
        --cards "$BotOS\done" "$BotOS\retros" "$Agency\projects" `
        --adr "$BotOS\decisions" `
        --brain-cases "$Brain\Cases" "$Brain\Knowledge\Malware cleanup" `
        --evalkit $EvalKit
    if ($LASTEXITCODE -ne 0) { throw "converter failed" }
}

Write-Host "`n== 1.3 clean / dedup / doctor / topics / split / canary"
soup data validate data\raw.jsonl
soup data clean data\raw.jsonl -o data\clean.jsonl
soup data dedup data\clean.jsonl --semantic --threshold 0.85 -o data\dedup.jsonl
soup data doctor data\dedup.jsonl --model $Model
soup data topics data\dedup.jsonl --clusters auto
soup data split data\dedup.jsonl --val 10 --test 10 --stratify cls
# split writes train/val/test next to the input; normalise names
Get-ChildItem data | Where-Object { $_.Name -match 'dedup.*(train|val|test)' } | ForEach-Object {
    $n = $Matches[1]; Move-Item $_.FullName "data\$n.jsonl" -Force
}
soup data canary insert data\train.jsonl -o data\train.canary.jsonl --manifest data\canary.json
Write-Host "`n!! data\canary.json is a SECRET (it proves memorisation). Keep it out of git and off the model."
soup data inspect data\train.jsonl
python tools\class-counts.py data\train.jsonl
Write-Host "`nNext (Phase 2): soup advise data\train.jsonl --goal `"answer Bot-OS extract/classify tasks as JSON, first try`" --probe"
