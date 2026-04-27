from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.helpers import get_message_text
from a2a.types import Message, Part
from google.protobuf.message import Message as ProtoMessage  # type: ignore[import-untyped]

from codex_a2a.a2a_proto import is_text_part, part_text, proto_to_python


def _extract_from_iterable(items: Any) -> str | None:
    if not isinstance(items, (list, tuple)):
        return None
    for item in items:
        extracted = extract_text_from_payload(item)
        if extracted:
            return extracted
    return None


def _extract_from_parts(parts: Any) -> str | None:
    if not isinstance(parts, (list, tuple)):
        return None
    if all(isinstance(part, Part) for part in parts):
        sdk_text = "\n".join(text for part in parts if (text := part_text(part)) and text.strip())
        if sdk_text:
            return sdk_text

    collected: list[str] = []
    for part in parts:
        if isinstance(part, Part) and is_text_part(part):
            if part.text:
                collected.append(part.text)
            continue
        if isinstance(part, Mapping):
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value.strip():
                collected.append(text_value)
                continue
            if isinstance(part.get("role"), str):
                nested = extract_text_from_payload(part)
                if nested:
                    collected.append(nested)
                    continue
    if collected:
        return "\n".join(collected)
    return None


def _extract_from_mapping(payload_map: Mapping[str, Any]) -> str | None:
    for key in (
        "content",
        "message",
        "messages",
        "result",
        "status",
        "text",
        "parts",
        "artifact",
        "artifacts",
        "history",
        "events",
        "root",
    ):
        if key not in payload_map:
            continue
        value = payload_map[key]
        if value in (None, ""):
            continue
        if key == "text" and isinstance(value, (str, int, float, bool)):
            text_value = str(value).strip()
            if text_value:
                return text_value
        if key == "parts":
            parts_text = _extract_from_parts(value)
            if parts_text:
                return parts_text
        if key == "artifact":
            artifact_text = extract_text_from_payload(value)
            if artifact_text:
                return artifact_text
        if isinstance(value, (list, tuple)) and key in (
            "messages",
            "artifacts",
            "history",
            "events",
        ):
            iterable_text = _extract_from_iterable(value)
            if iterable_text:
                return iterable_text
        nested_text = extract_text_from_payload(value)
        if nested_text:
            return nested_text
    return None


def extract_text_from_payload(payload: Any) -> str | None:
    if isinstance(payload, (list, tuple)):
        return _extract_from_iterable(payload)

    if isinstance(payload, Message):
        sdk_text = get_message_text(payload).strip()
        if sdk_text:
            return sdk_text
        return _extract_from_parts(payload.parts)

    if isinstance(payload, str):
        return payload.strip() or None

    status_payload = getattr(payload, "status", None)
    if status_payload is not None:
        text = extract_text_from_payload(status_payload)
        if text:
            return text

    message_payload = getattr(payload, "message", None)
    if message_payload is not None:
        text = extract_text_from_payload(message_payload)
        if text:
            return text

    task_payload = getattr(payload, "task", None)
    if task_payload is not None:
        text = extract_text_from_payload(task_payload)
        if text:
            return text

    status_update_payload = getattr(payload, "status_update", None)
    if status_update_payload is not None:
        text = extract_text_from_payload(status_update_payload)
        if text:
            return text

    artifact_update_payload = getattr(payload, "artifact_update", None)
    if artifact_update_payload is not None:
        text = extract_text_from_payload(artifact_update_payload)
        if text:
            return text

    artifact_payload = getattr(payload, "artifact", None)
    if artifact_payload is not None:
        text = extract_text_from_payload(artifact_payload)
        if text:
            return text

    result_payload = getattr(payload, "result", None)
    if result_payload is not None:
        text = extract_text_from_payload(result_payload)
        if text:
            return text

    history = getattr(payload, "history", None)
    if isinstance(history, (list, tuple)) and history:
        for item in reversed(history):
            text = extract_text_from_payload(item)
            if text:
                return text

    artifacts = getattr(payload, "artifacts", None)
    if isinstance(artifacts, (list, tuple)):
        for artifact in artifacts:
            artifact_parts = getattr(artifact, "parts", None)
            if isinstance(artifact_parts, (list, tuple)):
                text = _extract_from_parts(artifact_parts)
                if text:
                    return text

    text = _extract_from_parts(getattr(payload, "parts", None))
    if text:
        return text

    event_text = _extract_from_iterable(getattr(payload, "events", None))
    if event_text:
        return event_text

    if isinstance(payload, Mapping):
        mapped_text = _extract_from_mapping(payload)
        if mapped_text:
            return mapped_text

    mapping_payload = None
    if isinstance(payload, ProtoMessage):
        payload_dict = proto_to_python(payload)
        if isinstance(payload_dict, Mapping):
            mapping_payload = payload_dict
    elif hasattr(payload, "model_dump") and callable(payload.model_dump):
        payload_dict = payload.model_dump()
        if isinstance(payload_dict, Mapping):
            mapping_payload = payload_dict
    elif hasattr(payload, "dict") and callable(payload.dict):
        payload_dict = payload.dict()
        if isinstance(payload_dict, Mapping):
            mapping_payload = payload_dict
    elif isinstance(getattr(payload, "__dict__", None), Mapping):
        mapping_payload = dict(payload.__dict__)

    if mapping_payload is not None:
        mapped_text = _extract_from_mapping(mapping_payload)
        if mapped_text:
            return mapped_text

    return None
