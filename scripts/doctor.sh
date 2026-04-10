#!/usr/bin/env bash
# Run the default repository validation entrypoint.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "${SCRIPT_DIR}/validate_baseline.sh" "$@"
