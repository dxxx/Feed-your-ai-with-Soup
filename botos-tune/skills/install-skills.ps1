# Install the botos-tune skills into Claude Code on this PC (and optionally a Bot-OS copy).
#   powershell -ExecutionPolicy Bypass -File install-skills.ps1 [-BotOS "C:\Users\dXXX\Desktop\Bot-OS\Bot-OS"]
# Copies (not links) so a later git pull of the fork does not change a running skill silently.
param([string]$BotOS = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$targets = @("$env:USERPROFILE\.claude\skills")
if ($BotOS) { $targets += "$BotOS\skills" }   # Bot-OS test copy only; commit locally, never push upstream
foreach ($t in $targets) {
    Get-ChildItem $here -Directory | ForEach-Object {
        $dst = Join-Path $t $_.Name
        if (Test-Path "$dst\RULES.md") { Copy-Item "$dst\RULES.md" "$dst\RULES.md.bak" -Force }  # keep learned rules
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item "$($_.FullName)\*" $dst -Recurse -Force
        Write-Host "installed $($_.Name) -> $dst"
    }
}
Write-Host "RULES.md is the live, learned file: after a loop adds rules on the PC, copy it back into the fork and commit."
