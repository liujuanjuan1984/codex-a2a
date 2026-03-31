#!/usr/bin/env bash
# Sync a GitHub Release for an existing tag without re-publishing to PyPI.
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "gh not found in PATH" >&2
  exit 1
fi

python_bin="${PYTHON_BIN:-}"
if [[ -z "${python_bin}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  else
    echo "python3 or python not found in PATH" >&2
    exit 1
  fi
fi

release_tag="${RELEASE_TAG:-${1:-}}"
dist_dir="${DIST_DIR:-dist}"
retry_attempts="${RELEASE_RETRY_ATTEMPTS:-3}"
retry_delay_seconds="${RELEASE_RETRY_DELAY_SECONDS:-2}"

if [[ -z "${release_tag}" ]]; then
  echo "Set RELEASE_TAG or pass the tag name as the first argument." >&2
  exit 1
fi

if [[ ! -d "${dist_dir}" ]]; then
  echo "Distribution directory does not exist: ${dist_dir}" >&2
  exit 1
fi

shopt -s nullglob
release_assets=("${dist_dir}"/*.tar.gz "${dist_dir}"/*.whl)
shopt -u nullglob

if [[ "${#release_assets[@]}" -eq 0 ]]; then
  echo "No release assets found in ${dist_dir}" >&2
  exit 1
fi

retry() {
  local attempt=1
  local exit_code=0

  while true; do
    if "$@"; then
      return 0
    else
      exit_code=$?
    fi
    if (( attempt >= retry_attempts )); then
      echo "Command failed after ${attempt} attempts: $*" >&2
      return "${exit_code}"
    fi
    echo "Command failed with exit code ${exit_code}; retrying (${attempt}/${retry_attempts}): $*" >&2
    sleep $((retry_delay_seconds * attempt))
    attempt=$((attempt + 1))
  done
}

release_exists() {
  local attempt=1
  local stderr_file
  stderr_file="$(mktemp)"

  while true; do
    if gh release view "${release_tag}" >/dev/null 2>"${stderr_file}"; then
      rm -f "${stderr_file}"
      return 0
    fi

    if grep -Eqi "release[[:space:]]+not[[:space:]]+found|http 404" "${stderr_file}"; then
      rm -f "${stderr_file}"
      return 1
    fi

    if (( attempt >= retry_attempts )); then
      cat "${stderr_file}" >&2
      rm -f "${stderr_file}"
      return 2
    fi

    cat "${stderr_file}" >&2
    echo "Retrying release lookup (${attempt}/${retry_attempts}) for ${release_tag}" >&2
    rm -f "${stderr_file}"
    sleep $((retry_delay_seconds * attempt))
    stderr_file="$(mktemp)"
    attempt=$((attempt + 1))
  done
}

ensure_release_exists() {
  local exists_result=0

  if release_exists; then
    echo "GitHub Release already exists for ${release_tag}"
    return 0
  else
    exists_result=$?
  fi
  if (( exists_result != 1 )); then
    echo "Unable to determine whether GitHub Release ${release_tag} already exists" >&2
    return "${exists_result}"
  fi

  echo "Creating GitHub Release for ${release_tag}"
  retry gh release create "${release_tag}" --generate-notes --verify-tag
}

declare -A existing_release_assets=()

ensure_release_exists

release_assets_json="$(retry gh release view "${release_tag}" --json assets)"

while IFS= read -r asset_name; do
  if [[ -n "${asset_name}" ]]; then
    existing_release_assets["${asset_name}"]=1
  fi
done < <(
  printf "%s" "${release_assets_json}" | "${python_bin}" -c '
import json
import sys

release = json.load(sys.stdin)
for asset in release.get("assets", []):
    name = asset.get("name")
    if name:
        print(name)
'
)

for asset_path in "${release_assets[@]}"; do
  asset_name="$(basename "${asset_path}")"
  if [[ -n "${existing_release_assets[${asset_name}]:-}" ]]; then
    echo "Release asset already present: ${asset_name}"
    continue
  fi

  echo "Uploading release asset: ${asset_name}"
  retry gh release upload "${release_tag}" "${asset_path}"
  existing_release_assets["${asset_name}"]=1
done
