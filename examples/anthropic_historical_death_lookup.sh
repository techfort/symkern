#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT_DIR"

"$ROOT_DIR/.venv/bin/python" -m symkern.cli \
  create-program \
  --prompt "make up 3 historical dates, lookup on wikipedia.org what deaths occurred on those dates and elect the most illustrious one" \
  --translator anthropic \
  --translator-model claude-3-5-sonnet-latest \
  --translator-api-key-env ANTHROPIC_API_KEY