#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

cd "$ROOT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Python executable not found or not executable: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

if [[ $# -lt 1 ]]; then
  printf 'Usage: %s "PROMPT" [additional create-program args...]\n' "$0" >&2
  exit 1
fi

PROMPT="$1"
shift

printf 'Creating Symkern program from prompt in: %s\n' "$ROOT_DIR"

"$PYTHON_BIN" -m symkern.cli \
  create-program \
  --prompt "$PROMPT" \
  "$@"
