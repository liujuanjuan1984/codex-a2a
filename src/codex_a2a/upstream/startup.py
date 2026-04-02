from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from typing import Any

from codex_a2a.config import Settings
from codex_a2a.upstream.models import CodexStartupPrerequisiteError


def optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def build_startup_config_overrides(settings: Settings) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    profile = optional_string(settings.codex_profile)
    model = optional_string(settings.codex_model)
    model_explicit = "codex_model" in settings.model_fields_set

    if model is not None and (model_explicit or profile is None):
        overrides["model"] = model

    for key, value in (
        ("profile", profile),
        ("model_reasoning_effort", optional_string(settings.codex_model_reasoning_effort)),
        ("model_reasoning_summary", optional_string(settings.codex_model_reasoning_summary)),
        ("model_verbosity", optional_string(settings.codex_model_verbosity)),
        ("approval_policy", optional_string(settings.codex_approval_policy)),
        ("sandbox_mode", optional_string(settings.codex_sandbox_mode)),
        ("web_search", optional_string(settings.codex_web_search)),
        ("review_model", optional_string(settings.codex_review_model)),
    ):
        if value is not None:
            overrides[key] = value

    workspace_write: dict[str, Any] = {}
    if settings.codex_sandbox_workspace_write_writable_roots:
        workspace_write["writable_roots"] = list(
            settings.codex_sandbox_workspace_write_writable_roots
        )
    if settings.codex_sandbox_workspace_write_network_access is not None:
        workspace_write["network_access"] = settings.codex_sandbox_workspace_write_network_access
    if settings.codex_sandbox_workspace_write_exclude_slash_tmp is not None:
        workspace_write["exclude_slash_tmp"] = (
            settings.codex_sandbox_workspace_write_exclude_slash_tmp
        )
    if settings.codex_sandbox_workspace_write_exclude_tmpdir_env_var is not None:
        workspace_write["exclude_tmpdir_env_var"] = (
            settings.codex_sandbox_workspace_write_exclude_tmpdir_env_var
        )
    if workspace_write:
        overrides["sandbox_workspace_write"] = workspace_write
    return overrides


def build_cli_config_args(overrides: Mapping[str, Any]) -> list[str]:
    cli_args: list[str] = []
    for key, value in overrides.items():
        cli_args.extend(["-c", f"{key}={json.dumps(value)}"])
    return cli_args


def resolve_cli_bin(cli_bin: str) -> str:
    normalized_cli_bin = cli_bin.strip() or "codex"
    if os.path.sep in normalized_cli_bin or (
        os.path.altsep and os.path.altsep in normalized_cli_bin
    ):
        expanded = os.path.expanduser(normalized_cli_bin)
        if not os.path.exists(expanded):
            raise CodexStartupPrerequisiteError(
                f"Codex prerequisite not satisfied: CLI binary not found at "
                f"{expanded!r}. Install Codex or set CODEX_CLI_BIN to a valid "
                "executable."
            )
        if not os.access(expanded, os.X_OK):
            raise CodexStartupPrerequisiteError(
                f"Codex prerequisite not satisfied: CLI binary at {expanded!r} "
                "is not executable. Fix permissions or set CODEX_CLI_BIN to a "
                "valid executable."
            )
        return expanded

    resolved = shutil.which(normalized_cli_bin)
    if resolved is None and normalized_cli_bin == "codex":
        npm_global_bin = os.path.expanduser("~/.npm-global/bin/codex")
        if os.path.exists(npm_global_bin) and os.access(npm_global_bin, os.X_OK):
            resolved = npm_global_bin
    if resolved is None:
        raise CodexStartupPrerequisiteError(
            f"Codex prerequisite not satisfied: {normalized_cli_bin!r} was not found on "
            "PATH. Install Codex and verify the `codex` CLI is available "
            "before starting codex-a2a."
        )
    return resolved
