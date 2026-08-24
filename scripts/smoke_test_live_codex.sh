#!/usr/bin/env bash
# Verify the adapter can complete a real Codex app-server thread and turn.
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "codex not found in PATH" >&2
  exit 1
fi

codex --version
uv run python scripts/check_codex_app_server_schema.py --include-experimental
uv run python scripts/smoke_live_codex_turn.py

echo "Codex app-server stable/experimental schema and real thread/turn smoke tests passed."
