from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from a2a.server.agent_execution import RequestContext
from google.protobuf.message import Message as ProtoMessage  # type: ignore[import-untyped]

from codex_a2a.a2a_proto import proto_to_python
from codex_a2a.contracts.runtime_output import SHARED_METADATA_NAMESPACE
from codex_a2a.execution.request_overrides import (
    RequestExecutionOptions,
    RequestExecutionOptionsValidationError,
    build_request_execution_options,
)

logger = logging.getLogger(__name__)


def _metadata_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, ProtoMessage):
        proto_value = proto_to_python(value)
        return proto_value if isinstance(proto_value, Mapping) else None
    if not isinstance(value, Mapping):
        return None
    normalized_mapping: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(item, ProtoMessage):
            normalized_mapping[key] = proto_to_python(item)
            continue
        normalized_mapping[key] = item
    return normalized_mapping


def _append_metadata_candidate(
    candidates: list[Mapping[str, Any]],
    value: Any,
    *,
    source: str,
    purpose: str,
) -> None:
    try:
        candidate = _metadata_mapping(value)
    except Exception:
        # Request metadata comes from external clients and protobuf adapters, so normalization must
        # stay fail-open. We still log the failure at debug level to preserve diagnostics without
        # turning malformed metadata into a request-wide failure path.
        logger.debug(
            "Ignoring unparseable request metadata while extracting %s from %s",
            purpose,
            source,
            exc_info=True,
        )
        return
    if candidate is not None:
        candidates.append(candidate)


def _collect_metadata_candidates(
    context: RequestContext,
    *,
    purpose: str,
) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    _append_metadata_candidate(
        candidates,
        context.metadata,
        source="context.metadata",
        purpose=purpose,
    )
    if context.message is not None:
        _append_metadata_candidate(
            candidates,
            getattr(context.message, "metadata", None) or {},
            source="context.message.metadata",
            purpose=purpose,
        )
    return candidates


def extract_namespaced_string_metadata(
    context: RequestContext,
    *,
    namespace: str,
    path: tuple[str, ...],
) -> str | None:
    candidates = _collect_metadata_candidates(
        context,
        purpose=f"{namespace}.{'.'.join(path)}",
    )
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
    candidates = _collect_metadata_candidates(
        context,
        purpose="codex.execution options",
    )
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
