#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR"

"$ROOT_DIR/.venv/bin/python" -m symkern.cli \
  --prompt "Detect anomalies in a streaming signal with low false positives" \
  --translator openai-compatible \
  --translator-model gpt-4.1-mini \
  --translator-api-key-env OPENAI_API_KEY