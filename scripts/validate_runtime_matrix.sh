#!/usr/bin/env bash
# Run the reduced runtime-only validation used by the multi-version CI matrix.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found in PATH" >&2
  exit 1
fi

uv run pytest --no-cov
