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


def _apply_effective_model(
    params: dict[str, Any],
    *,
    execution_options: RequestExecutionOptions | None,
    default_model_id: str | None,
) -> None:
    effective_model = (
        execution_options.model
        if execution_options is not None and execution_options.model is not None
        else default_model_id
    )
    if effective_model:
        params["model"] = effective_model


def _project_present_fields(
    params: dict[str, Any] | None,
    field_map: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    projected: dict[str, Any] = {}
    for source_key, target_key in field_map:
        if source_key in params:
            projected[target_key] = params[source_key]
    return projected


def apply_thread_start_execution_options(
    params: dict[str, Any],
    *,
    execution_options: RequestExecutionOptions | None,
    default_model_id: str | None,
) -> dict[str, Any]:
    _apply_effective_model(
        params,
        execution_options=execution_options,
        default_model_id=default_model_id,
    )
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
    _apply_effective_model(
        params,
        execution_options=execution_options,
        default_model_id=default_model_id,
    )
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


def build_discovery_skills_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    rpc_params: dict[str, Any] = {}
    if "cwds" in params:
        rpc_params["cwds"] = params["cwds"]
    if "force_reload" in params:
        rpc_params["forceReload"] = params["force_reload"]
    extra_roots = params.get("per_cwd_extra_user_roots")
    if isinstance(extra_roots, list):
        rpc_params["perCwdExtraUserRoots"] = [
            {
                "cwd": item["cwd"],
                "extraUserRoots": item["extra_user_roots"],
            }
            for item in extra_roots
            if isinstance(item, dict) and "cwd" in item and "extra_user_roots" in item
        ]
    return rpc_params


def build_thread_rpc_params(
    thread_id: str,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    rpc_params: dict[str, Any] = {"threadId": thread_id}
    if not isinstance(params, dict):
        return rpc_params
    rpc_params.update(
        {
            key: value
            for key, value in params.items()
            if key not in {"directory", "git_info"} and value is not None
        }
    )
    git_info = params.get("git_info")
    if isinstance(git_info, dict):
        normalized_git_info = _project_present_fields(
            git_info,
            (
                ("branch", "branch"),
                ("sha", "sha"),
                ("origin_url", "originUrl"),
            ),
        )
        if normalized_git_info:
            rpc_params["gitInfo"] = normalized_git_info
    return rpc_params


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
