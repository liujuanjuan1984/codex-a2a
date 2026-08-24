#!/usr/bin/env bash
# Verify the adapter can complete a real Codex app-server thread and turn.
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "codex not found in PATH" >&2
  exit 1
fi

codex --version
uv run python scripts/smoke_live_codex_turn.py

echo "Real Codex app-server thread/turn smoke test passed."
