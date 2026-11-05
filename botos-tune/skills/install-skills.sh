#!/usr/bin/env bash
# Install the botos-tune skills into Claude Code (Linux/WSL/macOS). Usage: bash install-skills.sh [BOTOS_ROOT]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
targets=("$HOME/.claude/skills"); [ -n "${1:-}" ] && targets+=("$1/skills")
for t in "${targets[@]}"; do
  for d in "$here"/*/; do n=$(basename "$d"); mkdir -p "$t/$n"
    [ -f "$t/$n/RULES.md" ] && cp "$t/$n/RULES.md" "$t/$n/RULES.md.bak"
    cp -r "$d". "$t/$n/"; echo "installed $n -> $t/$n"; done
done
