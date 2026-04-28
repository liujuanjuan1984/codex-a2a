from __future__ import annotations

import shlex
from dataclasses import replace
from typing import Any

from codex_a2a.execution.request_overrides import RequestExecutionOptions


def coerce_request_execution_options(
    execution_options: RequestExecutionOptions | None,
) -> RequestExecutionOptions | None:
    if execution_options is None or execution_options.is_empty():
        return None
    return replace(execution_options)


def apply_thread_start_execution_options(
    params: dict[str, Any],
    *,
    execution_options: RequestExecutionOptions | None,
    default_model_id: str | None,
) -> dict[str, Any]:
    effective_model = (
        execution_options.model
        if execution_options is not None and execution_options.model is not None
        else default_model_id
    )
    if effective_model:
        params["model"] = effective_model
    if execution_options is None:
        return params
    if execution_options.personality is not None:
        params["personality"] = execution_options.personality
    return params


def apply_turn_start_execution_options(
    params: dict[str, Any],
    *,
    execution_options: RequestExecutionOptions | None,
    default_model_id: str | None,
) -> dict[str, Any]:
    effective_model = (
        execution_options.model
        if execution_options is not None and execution_options.model is not None
        else default_model_id
    )
    if effective_model:
        params["model"] = effective_model
    if execution_options is None:
        return params
    if execution_options.effort is not None:
        params["effort"] = execution_options.effort
    if execution_options.summary is not None:
        params["summary"] = execution_options.summary
    if execution_options.personality is not None:
        params["personality"] = execution_options.personality
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
