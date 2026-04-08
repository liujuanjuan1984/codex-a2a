from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_PERMISSION_INTERRUPT_METHOD_MAP = {
    "item/commandExecution/requestApproval": "command_execution",
    "execCommandApproval": "command_execution",
    "item/fileChange/requestApproval": "file_change",
    "applyPatchApproval": "apply_patch",
}


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _mapping_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _first_nested_string(payload: Mapping[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, Mapping):
                break
            current = current.get(key)
        else:
            value = _normalized_string(current)
            if value is not None:
                return value
    return None


def _extract_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _normalized_string(item)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    return values


def _extract_permission_patterns(params: dict[str, Any]) -> list[str]:
    patterns = _extract_string_list(params.get("patterns"))
    if patterns:
        return patterns

    parsed_cmd = params.get("parsedCmd")
    if not isinstance(parsed_cmd, list):
        return []

    resolved_patterns: list[str] = []
    seen: set[str] = set()
    for entry in parsed_cmd:
        if not isinstance(entry, Mapping):
            continue
        path = _normalized_string(entry.get("path"))
        if path is None or path in seen:
            continue
        seen.add(path)
        resolved_patterns.append(path)
    return resolved_patterns


def _extract_question_properties_questions(params: dict[str, Any]) -> list[Any]:
    questions = params.get("questions")
    if isinstance(questions, list):
        return questions

    context = _mapping_value(params.get("context"))
    if context is not None and isinstance(context.get("questions"), list):
        return context["questions"]
    return []


def _extract_mapping(params: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = _mapping_value(params.get(key))
    if value is None:
        return None
    return dict(value)


def resolve_permission_interrupt_semantic(method: str | None) -> str | None:
    normalized_method = _normalized_string(method)
    if normalized_method is None:
        return None
    return _PERMISSION_INTERRUPT_METHOD_MAP.get(normalized_method)


class InterruptRequestError(RuntimeError):
    def __init__(
        self,
        *,
        error_type: str,
        request_id: str,
        expected_interrupt_type: str | None = None,
        actual_interrupt_type: str | None = None,
    ) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.request_id = request_id
        self.expected_interrupt_type = expected_interrupt_type
        self.actual_interrupt_type = actual_interrupt_type


INTERRUPT_REQUEST_TOMBSTONE_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class InterruptRequestBinding:
    request_id: str
    interrupt_type: str
    session_id: str
    created_at: float
    expires_at: float | None = None
    identity: str | None = None
    credential_id: str | None = None
    task_id: str | None = None
    context_id: str | None = None


@dataclass(frozen=True)
class InterruptRequestTombstone:
    request_id: str
    expires_at: float


@dataclass
class _PendingInterruptRequest:
    binding: InterruptRequestBinding
    rpc_request_id: str | int
    params: dict[str, Any]


def build_codex_permission_interrupt_properties(
    *, request_key: str, session_id: str, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": request_key,
        "sessionID": session_id,
        "metadata": {"method": method, "raw": params},
    }
    display_message = _first_nested_string(
        params,
        ("request", "description"),
        ("description",),
        ("reason",),
        ("request", "reason"),
    )
    if display_message is not None:
        properties["display_message"] = display_message
    permission = resolve_permission_interrupt_semantic(method)
    if permission is not None:
        properties["permission"] = permission
    patterns = _extract_permission_patterns(params)
    if patterns:
        properties["patterns"] = patterns
    always = _extract_string_list(params.get("always"))
    if always:
        properties["always"] = always
    return properties


def build_codex_question_interrupt_properties(
    *, request_key: str, session_id: str, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    properties = {
        "id": request_key,
        "sessionID": session_id,
        "questions": _extract_question_properties_questions(params),
        "metadata": {"method": method, "raw": params},
    }
    display_message = _first_nested_string(
        params,
        ("description",),
        ("context", "description"),
        ("prompt",),
    )
    if display_message is not None:
        properties["display_message"] = display_message
    return properties


def build_codex_permissions_interrupt_properties(
    *, request_key: str, session_id: str, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": request_key,
        "sessionID": session_id,
        "metadata": {"method": method, "raw": params},
    }
    display_message = _first_nested_string(
        params,
        ("reason",),
        ("description",),
    )
    if display_message is not None:
        properties["display_message"] = display_message
    permissions = _extract_mapping(params, "permissions")
    if permissions is not None:
        properties["permissions"] = permissions
    return properties


def build_codex_elicitation_interrupt_properties(
    *, request_key: str, session_id: str, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": request_key,
        "sessionID": session_id,
        "metadata": {"method": method, "raw": params},
    }
    display_message = _first_nested_string(
        params,
        ("message",),
    )
    if display_message is not None:
        properties["display_message"] = display_message
    server_name = _normalized_string(params.get("serverName"))
    if server_name is not None:
        properties["server_name"] = server_name
    mode = _normalized_string(params.get("mode"))
    if mode is not None:
        properties["mode"] = mode
    requested_schema = _extract_mapping(params, "requestedSchema")
    if requested_schema is not None:
        properties["requested_schema"] = requested_schema
    url = _normalized_string(params.get("url"))
    if url is not None:
        properties["url"] = url
    elicitation_id = _normalized_string(params.get("elicitationId"))
    if elicitation_id is not None:
        properties["elicitation_id"] = elicitation_id
    meta = _extract_mapping(params, "_meta")
    if meta is not None:
        properties["meta"] = meta
    return properties


def interrupt_request_status(
    binding: InterruptRequestBinding,
    *,
    interrupt_request_ttl_seconds: int,
) -> str:
    expires_at = binding.expires_at
    if expires_at is None:
        expires_at = binding.created_at + float(interrupt_request_ttl_seconds)
    if expires_at <= time.time():
        return "expired"
    return "active"
