from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.server.agent_execution import RequestContext

from codex_a2a.contracts.runtime_output import SHARED_METADATA_NAMESPACE
from codex_a2a.execution.request_overrides import (
    RequestExecutionOptions,
    RequestExecutionOptionsValidationError,
    build_request_execution_options,
)


def extract_namespaced_string_metadata(
    context: RequestContext,
    *,
    namespace: str,
    path: tuple[str, ...],
) -> str | None:
    candidates: list[Mapping[str, Any]] = []
    try:
        meta = context.metadata
        if isinstance(meta, Mapping):
            candidates.append(meta)
    except Exception:
        pass

    if context.message is not None:
        message_metadata = getattr(context.message, "metadata", None) or {}
        if isinstance(message_metadata, Mapping):
            candidates.append(message_metadata)

    for candidate in candidates:
        current = candidate.get(namespace)
        for part in path[:-1]:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if not isinstance(current, Mapping):
            continue
        value = current.get(path[-1])
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def extract_shared_session_id(context: RequestContext) -> str | None:
    return extract_namespaced_string_metadata(
        context,
        namespace=SHARED_METADATA_NAMESPACE,
        path=("session", "id"),
    )


def extract_codex_directory(context: RequestContext) -> str | None:
    return extract_namespaced_string_metadata(
        context,
        namespace="codex",
        path=("directory",),
    )


def extract_codex_execution_options(context: RequestContext) -> RequestExecutionOptions:
    candidates: list[Mapping[str, Any]] = []
    try:
        meta = context.metadata
        if isinstance(meta, Mapping):
            candidates.append(meta)
    except Exception:
        pass

    if context.message is not None:
        message_metadata = getattr(context.message, "metadata", None) or {}
        if isinstance(message_metadata, Mapping):
            candidates.append(message_metadata)

    merged: dict[str, Any] = {}
    for candidate in candidates:
        codex = candidate.get("codex")
        if codex is None:
            continue
        if not isinstance(codex, Mapping):
            raise RequestExecutionOptionsValidationError(
                field="metadata.codex",
                message="metadata.codex must be an object",
            )
        execution = codex.get("execution")
        if execution is None:
            continue
        if not isinstance(execution, Mapping):
            raise RequestExecutionOptionsValidationError(
                field="metadata.codex.execution",
                message="metadata.codex.execution must be an object",
            )
        for field in ("model", "effort", "summary", "personality"):
            if field not in merged and field in execution:
                merged[field] = execution[field]

    return build_request_execution_options(
        model=merged.get("model"),
        effort=merged.get("effort"),
        summary=merged.get("summary"),
        personality=merged.get("personality"),
        field_prefix="metadata.codex.execution",
    )
