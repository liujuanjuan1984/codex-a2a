from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.helpers import get_artifact_text, get_message_text, get_stream_response_text
from a2a.types import Artifact, Message, Part, StreamResponse, Task, TaskArtifactUpdateEvent

from codex_a2a.a2a_proto import is_text_part, part_text


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


def extract_text_from_payload(payload: Any) -> str | None:
    if isinstance(payload, StreamResponse):
        sdk_text = get_stream_response_text(payload).strip()
        if sdk_text:
            return sdk_text
        return _extract_from_stream_response(payload)

    if isinstance(payload, Message):
        sdk_text = get_message_text(payload).strip()
        if sdk_text:
            return sdk_text
        return _extract_from_parts(payload.parts)

    if isinstance(payload, Task):
        status_payload = payload.status
        if status_payload is not None and status_payload.message is not None:
            text = extract_text_from_payload(status_payload.message)
            if text:
                return text
        for artifact in payload.artifacts:
            text = extract_text_from_payload(artifact)
            if text:
                return text
        return None

    if isinstance(payload, Artifact):
        sdk_text = get_artifact_text(payload).strip()
        if sdk_text:
            return sdk_text
        return _extract_from_parts(payload.parts)

    if isinstance(payload, TaskArtifactUpdateEvent):
        return extract_text_from_payload(payload.artifact)

    return None


def _extract_from_stream_response(payload: StreamResponse) -> str | None:
    if payload.HasField("artifact_update"):
        return extract_text_from_payload(payload.artifact_update.artifact)
    if payload.HasField("message"):
        return extract_text_from_payload(payload.message)
    if payload.HasField("task"):
        return extract_text_from_payload(payload.task)
    if payload.HasField("status_update") and payload.status_update.status.message is not None:
        return extract_text_from_payload(payload.status_update.status.message)
    return None
