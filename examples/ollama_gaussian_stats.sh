#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

cd "$ROOT_DIR"

printf 'Running Symkern Ollama example from: %s\n' "$ROOT_DIR"
printf 'Using Python executable: %s\n' "$PYTHON_BIN"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Python executable not found or not executable: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" -m symkern.cli \
  create-program \
  --prompt "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median." \
  --translator ollama \
  --ollama-model llama3.1:8b

printf '\nArtifacts are written under: %s\n' "$ROOT_DIR/artifacts"