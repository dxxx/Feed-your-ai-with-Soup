# Bot-OS × Soup — Phase 1.1: install Soup on RYZEN9 (Windows, PowerShell 5.1+)
# Run once:  powershell -ExecutionPolicy Bypass -File install-soup.ps1
# Idempotent. Uses `python` (3.13.7), never the Store `python3` stub.

$ErrorActionPreference = "Stop"
$Root = "E:\Local-AI\soup"
$Tune = "E:\Local-AI\botos-tune"

Write-Host "== Soup install -> $Root"
New-Item -ItemType Directory -Force -Path $Root, $Tune, "$Tune\data", "$Tune\runs", "$Tune\evals", "$Tune\tools" | Out-Null

$py = (Get-Command python -ErrorAction Stop).Source
Write-Host "python: $py ($(& python --version))"
if (-not (Test-Path "$Root\.venv")) { & python -m venv "$Root\.venv" }
& "$Root\.venv\Scripts\python.exe" -m pip install --upgrade pip -q
# [train] = torch/transformers/peft/trl/bitsandbytes; [mcp] = `soup mcp serve` for Phase 6
& "$Root\.venv\Scripts\python.exe" -m pip install "soup-cli[train,mcp]" -q
& "$Root\.venv\Scripts\soup.exe" --version

# Copy the kit from the fork checkout next to this script into the build folder
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Copy-Item "$here\tools\*.py" "$Tune\tools\" -Force
foreach ($f in "soup.yaml", "deny-list.txt", "run-phase1.ps1", "BASELINE.md", "README.md") {
    if (-not (Test-Path "$Tune\$f")) { Copy-Item "$here\$f" "$Tune\$f" }
}
Copy-Item "$here\evals\*" "$Tune\evals\" -Force

# GPU sanity (does not download the model)
& "$Root\.venv\Scripts\python.exe" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
Write-Host "`nIf cuda is False: pip install torch --index-url https://download.pytorch.org/whl/cu128 inside the venv."
Write-Host "If bitsandbytes 4-bit fails on Windows: set training.quantization: none and lora.r: 16 in soup.yaml, or train under WSL2."

Write-Host "`nNext: activate with  $Root\.venv\Scripts\Activate.ps1  then  cd $Tune ; .\run-phase1.ps1"
