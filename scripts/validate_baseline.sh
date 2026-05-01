#!/usr/bin/env bash
# Run the default local validation baseline in the same order as CI.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found in PATH" >&2
  exit 1
fi

run_pip_audit() {
  local requirement_file="$1"
  local attempt=1
  local max_attempts=3
  local status=0

  while true; do
    if uv run pip-audit --requirement "${requirement_file}"; then
      return 0
    fi
    status=$?
    if [[ "${attempt}" -ge "${max_attempts}" ]]; then
      echo "pip-audit failed after ${attempt} attempts" >&2
      return "${status}"
    fi
    echo "pip-audit failed on attempt ${attempt}/${max_attempts}; retrying..." >&2
    attempt=$((attempt + 1))
    sleep 2
  done
}

uv run pre-commit run --all-files
uv run python scripts/check_dead_code.py
uv run mypy --config-file mypy.ini
uv run pytest

runtime_requirements="$(mktemp)"
trap 'rm -f "${runtime_requirements}"' EXIT

uv export \
  --format requirements.txt \
  --no-dev \
  --locked \
  --no-emit-project \
  --output-file "${runtime_requirements}" >/dev/null

run_pip_audit "${runtime_requirements}"

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
