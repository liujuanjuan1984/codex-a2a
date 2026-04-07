from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from codex_a2a.upstream.interrupts import resolve_permission_interrupt_semantic

_INTERRUPT_ASKED_EVENT_TYPES = {
    "permission.asked",
    "question.asked",
    "permissions.asked",
    "elicitation.asked",
}
_INTERRUPT_RESOLVED_EVENT_TYPES = {
    "permission.replied",
    "question.replied",
    "question.rejected",
    "permissions.replied",
    "elicitation.replied",
    "elicitation.rejected",
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


def _nested_value(root: Mapping[str, Any], *path: str) -> Any:
    current: Any = root
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first_nested_string(root: Mapping[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = _normalized_string(_nested_value(root, *path))
        if value is not None:
            return value
    return None


def extract_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def extract_interrupt_text_details(props: Mapping[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    display_message = _first_nested_string(
        props,
        ("display_message",),
        ("message",),
        ("description",),
        ("request", "description"),
        ("context", "description"),
        ("reason",),
        ("request", "reason"),
        ("metadata", "raw", "message"),
        ("metadata", "raw", "description"),
        ("metadata", "raw", "request", "description"),
        ("metadata", "raw", "context", "description"),
        ("metadata", "raw", "prompt"),
        ("metadata", "raw", "reason"),
        ("metadata", "raw", "request", "reason"),
    )
    if display_message is not None:
        details["display_message"] = display_message
    return details


def extract_interrupt_questions(props: Mapping[str, Any]) -> list[Any]:
    questions = _nested_value(props, "questions")
    if isinstance(questions, list):
        return questions
    nested_questions = _nested_value(props, "context", "questions")
    if isinstance(nested_questions, list):
        return nested_questions
    raw_questions = _nested_value(props, "metadata", "raw", "questions")
    if isinstance(raw_questions, list):
        return raw_questions
    raw_nested_questions = _nested_value(props, "metadata", "raw", "context", "questions")
    if isinstance(raw_nested_questions, list):
        return raw_nested_questions
    return []


def extract_interrupt_permissions(props: Mapping[str, Any]) -> dict[str, Any] | None:
    permissions = _nested_value(props, "permissions")
    if isinstance(permissions, Mapping):
        return dict(permissions)
    raw_permissions = _nested_value(props, "metadata", "raw", "permissions")
    if isinstance(raw_permissions, Mapping):
        return dict(raw_permissions)
    return None


def extract_interrupt_patterns(props: Mapping[str, Any]) -> list[str]:
    patterns = extract_string_list(_nested_value(props, "patterns"))
    if patterns:
        return patterns

    raw_patterns = extract_string_list(_nested_value(props, "metadata", "raw", "patterns"))
    if raw_patterns:
        return raw_patterns

    fallback_path = _first_nested_string(
        props,
        ("metadata", "path"),
        ("path",),
        ("metadata", "raw", "path"),
    )
    if fallback_path is not None:
        return [fallback_path]

    parsed_cmd = _nested_value(props, "metadata", "raw", "parsedCmd")
    if not isinstance(parsed_cmd, list):
        return []

    resolved_patterns: list[str] = []
    seen: set[str] = set()
    for entry in parsed_cmd:
        mapping = _mapping_value(entry)
        if mapping is None:
            continue
        path = _normalized_string(mapping.get("path"))
        if path is None or path in seen:
            continue
        seen.add(path)
        resolved_patterns.append(path)
    return resolved_patterns


def diagnose_interrupt_event(event: Mapping[str, Any]) -> str | None:
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None
    if event_type in _INTERRUPT_ASKED_EVENT_TYPES:
        props = event.get("properties")
        if not isinstance(props, Mapping):
            return "interrupt asked event missing properties mapping"
        request_id = props.get("id")
        if not isinstance(request_id, str) or not request_id.strip():
            return "interrupt asked event missing request id"
        return None
    if event_type in _INTERRUPT_RESOLVED_EVENT_TYPES:
        props = event.get("properties")
        if not isinstance(props, Mapping):
            return "interrupt resolved event missing properties mapping"
        request_id = props.get("requestID") or props.get("id")
        if not isinstance(request_id, str) or not request_id.strip():
            return "interrupt resolved event missing request id"
        return None
    if event_type.startswith(("permission.", "question.", "permissions.", "elicitation.")):
        return f"unsupported interrupt event type: {event_type}"
    return None


def extract_interrupt_asked_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    if event_type not in _INTERRUPT_ASKED_EVENT_TYPES:
        return None
    props = event.get("properties")
    if not isinstance(props, Mapping):
        return None
    request_id = props.get("id")
    if not isinstance(request_id, str):
        return None
    normalized_request_id = request_id.strip()
    if not normalized_request_id:
        return None
    if event_type == "permission.asked":
        permission = _first_nested_string(
            props,
            ("permission",),
            ("metadata", "raw", "permission"),
        ) or resolve_permission_interrupt_semantic(
            _first_nested_string(
                props,
                ("metadata", "method"),
            )
        )
        details: dict[str, Any] = {
            "permission": permission,
            "patterns": extract_interrupt_patterns(props),
            "always": extract_string_list(_nested_value(props, "always"))
            or extract_string_list(_nested_value(props, "metadata", "raw", "always")),
        }
        details.update(extract_interrupt_text_details(props))
        return {
            "request_id": normalized_request_id,
            "interrupt_type": "permission",
            "details": details,
        }
    if event_type == "permissions.asked":
        details = {"permissions": extract_interrupt_permissions(props)}
        details.update(extract_interrupt_text_details(props))
        return {
            "request_id": normalized_request_id,
            "interrupt_type": "permissions",
            "details": details,
        }
    if event_type == "elicitation.asked":
        details = {
            "server_name": _first_nested_string(
                props,
                ("server_name",),
                ("metadata", "raw", "serverName"),
            ),
            "mode": _first_nested_string(
                props,
                ("mode",),
                ("metadata", "raw", "mode"),
            ),
            "requested_schema": _nested_value(props, "requested_schema")
            or _nested_value(props, "metadata", "raw", "requestedSchema"),
            "url": _first_nested_string(
                props,
                ("url",),
                ("metadata", "raw", "url"),
            ),
            "elicitation_id": _first_nested_string(
                props,
                ("elicitation_id",),
                ("metadata", "raw", "elicitationId"),
            ),
        }
        meta = _nested_value(props, "meta") or _nested_value(props, "metadata", "raw", "_meta")
        if isinstance(meta, Mapping):
            details["meta"] = dict(meta)
        details.update(extract_interrupt_text_details(props))
        return {
            "request_id": normalized_request_id,
            "interrupt_type": "elicitation",
            "details": details,
        }
    details = {"questions": extract_interrupt_questions(props)}
    details.update(extract_interrupt_text_details(props))
    return {
        "request_id": normalized_request_id,
        "interrupt_type": "question",
        "details": details,
    }


def extract_interrupt_resolved_event(event: Mapping[str, Any]) -> dict[str, str] | None:
    event_type = event.get("type")
    if event_type not in _INTERRUPT_RESOLVED_EVENT_TYPES:
        return None
    props = event.get("properties")
    if not isinstance(props, Mapping):
        return None
    request_id = props.get("requestID") or props.get("id")
    if not isinstance(request_id, str):
        return None
    normalized_request_id = request_id.strip()
    if not normalized_request_id:
        return None
    if event_type == "permission.replied":
        return {
            "request_id": normalized_request_id,
            "event_type": event_type,
            "interrupt_type": "permission",
            "resolution": "replied",
        }
    if event_type == "permissions.replied":
        return {
            "request_id": normalized_request_id,
            "event_type": event_type,
            "interrupt_type": "permissions",
            "resolution": "replied",
        }
    if event_type == "question.rejected":
        return {
            "request_id": normalized_request_id,
            "event_type": event_type,
            "interrupt_type": "question",
            "resolution": "rejected",
        }
    if event_type == "elicitation.rejected":
        return {
            "request_id": normalized_request_id,
            "event_type": event_type,
            "interrupt_type": "elicitation",
            "resolution": "rejected",
        }
    if event_type == "elicitation.replied":
        return {
            "request_id": normalized_request_id,
            "event_type": event_type,
            "interrupt_type": "elicitation",
            "resolution": "replied",
        }
    return {
        "request_id": normalized_request_id,
        "event_type": event_type,
        "interrupt_type": "question",
        "resolution": "replied",
    }
