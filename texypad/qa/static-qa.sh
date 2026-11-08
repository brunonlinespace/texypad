#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROGRAM_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
PROJECT_ROOT="$(cd -- "$PROGRAM_ROOT/.." && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
PYTHONPATH="$PROJECT_ROOT" python3 "$SCRIPT_DIR/release_check.py"
PYTHONPATH="$PROJECT_ROOT" python3 -m unittest discover -s "$PROGRAM_ROOT/tests" -v
