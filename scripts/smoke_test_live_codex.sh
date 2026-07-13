#!/usr/bin/env bash
# Verify the adapter can initialize and close a real Codex app-server process.
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "codex not found in PATH" >&2
  exit 1
fi

codex --version

uv run python - <<'PY'
from __future__ import annotations

import asyncio

from codex_a2a.config import Settings
from codex_a2a.upstream.client import CodexClient


async def main() -> None:
    settings = Settings.model_validate(
        {
            "a2a_static_auth_credentials": [
                {
                    "id": "live-smoke",
                    "scheme": "bearer",
                    "token": "local-live-smoke-token",
                    "principal": "live-smoke",
                }
            ],
            "a2a_database_url": None,
            "codex_cli_bin": "codex",
            "codex_timeout": 30.0,
        }
    )
    client = CodexClient(settings)
    try:
        await asyncio.wait_for(client.startup_preflight(), timeout=45.0)
    finally:
        await client.close()


asyncio.run(main())
PY

echo "Real Codex app-server initialization smoke test passed."
