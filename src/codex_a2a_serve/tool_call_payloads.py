from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

ToolCallKind = Literal["state", "output_delta"]
ToolCallSourceMethod = Literal["commandExecution", "fileChange"]


class ToolCallStatePayload(TypedDict, total=False):
    kind: Literal["state"]
    source_method: str
    call_id: str
    tool: str
    status: str
    title: Any
    subtitle: Any
    input: Any
    output: Any
    error: Any


class ToolCallOutputDeltaPayload(TypedDict, total=False):
    kind: Literal["output_delta"]
    source_method: str
    call_id: str
    tool: str
    status: str
    output_delta: str


ToolCallPayload = ToolCallStatePayload | ToolCallOutputDeltaPayload


def serialize_tool_call_payload(payload: ToolCallPayload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_tool_call_payload(payload: Mapping[str, Any]) -> ToolCallPayload | None:
    kind = _extract_nonempty_string(payload, "kind")
    if kind == "state":
        return _normalize_state_payload(payload)
    if kind == "output_delta":
        return _normalize_output_delta_payload(payload)
    return None


def tool_call_state_payload_from_part(part: Mapping[str, Any]) -> ToolCallStatePayload | None:
    payload: ToolCallStatePayload = {"kind": "state"}

    call_id = _extract_nonempty_string(part, "callID", "callId", "call_id")
    if call_id is not None:
        payload["call_id"] = call_id

    tool = _extract_nonempty_string(part, "tool", "name")
    if tool is not None:
        payload["tool"] = tool

    source_method = _extract_nonempty_string(part, "sourceMethod", "source_method")
    if source_method is not None:
        payload["source_method"] = source_method

    state = part.get("state")
    if isinstance(state, Mapping):
        status = _extract_nonempty_string(state, "status")
        if status is not None:
            payload["status"] = status
        for key in ("title", "subtitle", "input", "output", "error"):
            value = state.get(key)
            if value is not None:
                payload[key] = value

    if len(payload) == 1:
        return None
    return payload


def tool_call_output_delta_payload_from_notification(
    *,
    source_method: ToolCallSourceMethod,
    delta: str,
    call_id: str | None = None,
    tool: str | None = None,
    status: str | None = None,
) -> ToolCallOutputDeltaPayload | None:
    if delta == "":
        return None

    payload: ToolCallOutputDeltaPayload = {
        "kind": "output_delta",
        "source_method": source_method,
        "output_delta": delta,
    }
    if call_id is not None:
        payload["call_id"] = call_id
    if tool is not None:
        payload["tool"] = tool
    if status is not None:
        payload["status"] = status
    return payload


def _normalize_state_payload(payload: Mapping[str, Any]) -> ToolCallStatePayload | None:
    normalized: ToolCallStatePayload = {"kind": "state"}

    source_method = _extract_nonempty_string(payload, "source_method")
    if source_method is not None:
        normalized["source_method"] = source_method

    call_id = _extract_nonempty_string(payload, "call_id")
    if call_id is not None:
        normalized["call_id"] = call_id

    tool = _extract_nonempty_string(payload, "tool")
    if tool is not None:
        normalized["tool"] = tool

    status = _extract_nonempty_string(payload, "status")
    if status is not None:
        normalized["status"] = status

    for key in ("title", "subtitle", "input", "output", "error"):
        value = payload.get(key)
        if value is not None:
            normalized[key] = value

    if len(normalized) == 1:
        return None
    return normalized


def _normalize_output_delta_payload(payload: Mapping[str, Any]) -> ToolCallOutputDeltaPayload | None:
    output_delta = payload.get("output_delta")
    if not isinstance(output_delta, str) or output_delta == "":
        return None

    normalized: ToolCallOutputDeltaPayload = {
        "kind": "output_delta",
        "output_delta": output_delta,
    }

    source_method = _extract_nonempty_string(payload, "source_method")
    if source_method is not None:
        normalized["source_method"] = source_method

    call_id = _extract_nonempty_string(payload, "call_id")
    if call_id is not None:
        normalized["call_id"] = call_id

    tool = _extract_nonempty_string(payload, "tool")
    if tool is not None:
        normalized["tool"] = tool

    status = _extract_nonempty_string(payload, "status")
    if status is not None:
        normalized["status"] = status

    return normalized


def _extract_nonempty_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def as_tool_call_payload(payload: ToolCallPayload) -> dict[str, Any]:
    return cast(dict[str, Any], payload)
