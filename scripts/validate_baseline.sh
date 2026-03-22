#!/usr/bin/env bash
# Run the default local validation baseline in the same order as CI.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found in PATH" >&2
  exit 1
fi

uv run pre-commit run --all-files
uv run mypy --config-file mypy.ini
uv run pytest

rm -f dist/codex_a2a-*.whl dist/codex_a2a-*.tar.gz
uv build --no-sources

shopt -s nullglob
wheel_paths=(dist/codex_a2a-*.whl)
shopt -u nullglob

if [[ "${#wheel_paths[@]}" -ne 1 ]]; then
  echo "Expected exactly one built wheel in dist/, found ${#wheel_paths[@]}" >&2
  exit 1
fi

WHEEL_PATH="${wheel_paths[0]}" bash ./scripts/smoke_test_built_cli.sh
