#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
for script in scripts/*.sh; do
  bash -n "$script"
done
shellcheck scripts/*.sh
python3 -B -c 'import ast, pathlib; [ast.parse(p.read_text(), filename=str(p)) for root in ("scripts", "tests") for p in pathlib.Path(root).glob("*.py")]'
unit_dir="$(mktemp -d)"
trap 'rm -rf "$unit_dir"' EXIT
python3 -B scripts/browser_runtime.py render-units "$unit_dir"
XDG_RUNTIME_DIR="$unit_dir" systemd-analyze --user verify "$unit_dir"/*.service "$unit_dir"/*.target
git diff --check
