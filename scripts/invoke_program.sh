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
  printf 'Usage: %s MACHINE_CODE_PATH [--input-json JSON | --input-file PATH] [additional invoke-program args...]\n' "$0" >&2
  exit 1
fi

MACHINE_CODE_PATH="$1"
shift

printf 'Invoking Symkern program from machine code: %s\n' "$MACHINE_CODE_PATH"

"$PYTHON_BIN" -m symkern.cli \
  invoke-program \
  --machine-code "$MACHINE_CODE_PATH" \
  "$@"
