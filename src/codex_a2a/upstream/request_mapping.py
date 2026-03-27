from __future__ import annotations

import shlex
from typing import Any

from codex_a2a.input_mapping import (
    convert_request_parts_to_turn_input as _convert_request_parts_to_turn_input,
)


def convert_request_parts_to_turn_input(request: dict[str, Any]) -> list[dict[str, Any]]:
    return _convert_request_parts_to_turn_input(request)


def format_shell_response(result: dict[str, Any]) -> str:
    exit_code = result.get("exitCode")
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    lines: list[str] = [f"exit_code: {exit_code}"]
    if isinstance(stdout, str) and stdout:
        lines.append("stdout:")
        lines.append(stdout.rstrip())
    if isinstance(stderr, str) and stderr:
        lines.append("stderr:")
        lines.append(stderr.rstrip())
    return "\n".join(lines)


def build_shell_exec_params(
    *,
    command_text: str,
    directory: str | None,
    default_workspace_root: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"command": shlex.split(command_text)}
    if directory:
        params["cwd"] = directory
    elif default_workspace_root:
        params["cwd"] = default_workspace_root
    return params


def build_interactive_exec_params(
    *,
    command_text: str,
    arguments: str | None,
    process_id: str,
    directory: str | None,
    default_workspace_root: str | None,
    tty: bool,
    rows: int | None,
    cols: int | None,
    output_bytes_cap: int | None,
    disable_output_cap: bool | None,
    timeout_ms: int | None,
    disable_timeout: bool | None,
) -> dict[str, Any]:
    argv = shlex.split(command_text)
    if arguments:
        argv.extend(shlex.split(arguments))
    params: dict[str, Any] = {
        "command": argv,
        "processId": process_id,
        "tty": tty,
        "streamStdin": True,
        "streamStdoutStderr": True,
    }
    if directory:
        params["cwd"] = directory
    elif default_workspace_root:
        params["cwd"] = default_workspace_root
    if rows is not None and cols is not None:
        params["size"] = {"rows": rows, "cols": cols}
    if output_bytes_cap is not None:
        params["outputBytesCap"] = output_bytes_cap
    if disable_output_cap is not None:
        params["disableOutputCap"] = disable_output_cap
    if timeout_ms is not None:
        params["timeoutMs"] = timeout_ms
    if disable_timeout is not None:
        params["disableTimeout"] = disable_timeout
    return params


def format_exec_result_text(result: dict[str, Any]) -> str:
    exit_code = result.get("exitCode")
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    lines: list[str] = [f"exit_code: {exit_code}"]
    if isinstance(stdout, str) and stdout:
        lines.append("stdout:")
        lines.append(stdout.rstrip())
    if isinstance(stderr, str) and stderr:
        lines.append("stderr:")
        lines.append(stderr.rstrip())
    return "\n".join(lines)


def uuid_like_suffix(value: str) -> str:
    normalized = value.strip().replace(" ", "-")
    if not normalized:
        return "empty"
    return normalized[:32]
