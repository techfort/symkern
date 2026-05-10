#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR"

"$ROOT_DIR/.venv/bin/python" -m symkern.cli \
  --prompt "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median." \
  --translator ollama \
  --ollama-model llama3.1:8b