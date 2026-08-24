#!/usr/bin/env python3
"""Check the installed Codex App Server schema against adapter dependencies."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

STABLE_PROTOCOL_TOKENS = frozenset(
    {
        "app/list",
        "command/exec",
        "command/exec/resize",
        "command/exec/terminate",
        "command/exec/write",
        "item/agentMessage/delta",
        "review/start",
        "skills/list",
        "thread/archive",
        "thread/fork",
        "thread/list",
        "thread/loaded/list",
        "thread/metadata/update",
        "thread/read",
        "thread/resume",
        "thread/start",
        "thread/unarchive",
        "turn/completed",
        "turn/start",
        "turn/steer",
    }
)
EXPERIMENTAL_PROTOCOL_TOKENS = frozenset({"plugin/list", "plugin/read"})


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def collect_schema_tokens(schema_dir: Path) -> set[str]:
    tokens: set[str] = set()
    schema_paths = sorted(schema_dir.rglob("*.json"))
    if not schema_paths:
        raise ValueError(f"Codex did not generate JSON schema files in {schema_dir}")
    for schema_path in schema_paths:
        with schema_path.open(encoding="utf-8") as schema_file:
            tokens.update(_iter_strings(json.load(schema_file)))
    return tokens


def missing_protocol_tokens(tokens: set[str], *, include_experimental: bool) -> list[str]:
    required = set(STABLE_PROTOCOL_TOKENS)
    if include_experimental:
        required.update(EXPERIMENTAL_PROTOCOL_TOKENS)
    return sorted(required - tokens)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--include-experimental",
        action="store_true",
        help="also require the opt-in plugin/list and plugin/read contracts",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="codex-app-server-schema-") as temp_dir:
        schema_dir = Path(temp_dir)
        subprocess.run(  # noqa: S603 - maintainer-selected local Codex executable
            [
                args.codex_bin,
                "app-server",
                "generate-json-schema",
                "--out",
                str(schema_dir),
            ],
            check=True,
        )
        missing = missing_protocol_tokens(
            collect_schema_tokens(schema_dir),
            include_experimental=args.include_experimental,
        )

    if missing:
        print("Codex App Server schema is missing adapter protocol tokens:")
        for token in missing:
            print(f"- {token}")
        return 1

    maturity = "stable and experimental" if args.include_experimental else "stable"
    print(f"Codex App Server {maturity} schema contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
