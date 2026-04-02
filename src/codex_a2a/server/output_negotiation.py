from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from a2a.types import (
    Artifact,
    DataPart,
    FilePart,
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
)

from codex_a2a.media_modes import (
    APPLICATION_JSON_MEDIA_MODE,
    TEXT_PLAIN_MEDIA_MODE,
)


def normalize_accepted_output_modes(
    accepted_output_modes: Iterable[str] | None,
) -> frozenset[str] | None:
    if accepted_output_modes is None:
        return None

    normalized = frozenset(
        mode.strip() for mode in accepted_output_modes if isinstance(mode, str) and mode.strip()
    )
    if not normalized or "*/*" in normalized or "*" in normalized:
        return None
    return normalized


def apply_accepted_output_modes(
    payload: Any,
    accepted_output_modes: Iterable[str] | None,
) -> Any | None:
    accepted_modes = normalize_accepted_output_modes(accepted_output_modes)
    if accepted_modes is None:
        return payload

    if isinstance(payload, TaskArtifactUpdateEvent):
        artifact = _filter_artifact(payload.artifact, accepted_modes)
        if artifact is None:
            return None
        return payload.model_copy(update={"artifact": artifact})

    if isinstance(payload, TaskStatusUpdateEvent):
        status = payload.status
        message = _filter_optional_message(status.message, accepted_modes)
        return payload.model_copy(update={"status": status.model_copy(update={"message": message})})

    if isinstance(payload, Task):
        return _filter_task(payload, accepted_modes)

    if isinstance(payload, Message):
        filtered = _filter_message(payload, accepted_modes)
        if filtered is not None:
            return filtered
        return payload.model_copy(update={"parts": []})

    return payload


def _filter_task(task: Task, accepted_modes: frozenset[str]) -> Task:
    filtered_history: list[Message] = []
    for message in task.history or []:
        filtered_message = _filter_message(message, accepted_modes)
        if filtered_message is not None:
            filtered_history.append(filtered_message)

    filtered_artifacts: list[Artifact] = []
    for artifact in task.artifacts or []:
        filtered_artifact = _filter_artifact(artifact, accepted_modes)
        if filtered_artifact is not None:
            filtered_artifacts.append(filtered_artifact)

    filtered_status_message = _filter_optional_message(task.status.message, accepted_modes)
    return task.model_copy(
        update={
            "history": filtered_history,
            "artifacts": filtered_artifacts,
            "status": task.status.model_copy(update={"message": filtered_status_message}),
        }
    )


def _filter_optional_message(
    message: Message | None,
    accepted_modes: frozenset[str],
) -> Message | None:
    if message is None:
        return None
    return _filter_message(message, accepted_modes)


def _filter_message(
    message: Message,
    accepted_modes: frozenset[str],
) -> Message | None:
    filtered_parts = _filter_parts(message.parts or [], accepted_modes)
    if not filtered_parts:
        return None
    return message.model_copy(update={"parts": filtered_parts})


def _filter_artifact(
    artifact: Artifact,
    accepted_modes: frozenset[str],
) -> Artifact | None:
    filtered_parts = _filter_parts(artifact.parts or [], accepted_modes)
    if not filtered_parts:
        return None
    return artifact.model_copy(update={"parts": filtered_parts})


def _filter_parts(parts: list[Part], accepted_modes: frozenset[str]) -> list[Part]:
    filtered_parts: list[Part] = []
    for part in parts:
        root = getattr(part, "root", None)
        media_mode = _part_media_mode(root)
        if media_mode is not None and _mode_is_accepted(media_mode, accepted_modes):
            filtered_parts.append(part)
            continue

        if _mode_is_accepted(TEXT_PLAIN_MEDIA_MODE, accepted_modes):
            fallback_text = _part_text_fallback(root)
            if fallback_text is not None:
                filtered_parts.append(Part(root=TextPart(text=fallback_text)))
    return filtered_parts


def _part_media_mode(part: Any) -> str | None:
    if isinstance(part, TextPart):
        return TEXT_PLAIN_MEDIA_MODE
    if isinstance(part, DataPart):
        return APPLICATION_JSON_MEDIA_MODE
    if isinstance(part, FilePart):
        payload = part.file
        mime_type = _file_payload_value(payload, "mimeType", "mime_type")
        if isinstance(mime_type, str) and mime_type.strip():
            return mime_type.strip()
        uri = _file_payload_value(payload, "uri")
        if isinstance(uri, str) and uri.startswith("data:image/"):
            return uri.removeprefix("data:").split(";", 1)[0]
    return None


def _mode_is_accepted(media_mode: str, accepted_modes: frozenset[str]) -> bool:
    if media_mode in accepted_modes:
        return True

    try:
        media_type, media_subtype = media_mode.split("/", 1)
    except ValueError:
        return False

    wildcard = f"{media_type}/*"
    return wildcard in accepted_modes or f"*/{media_subtype}" in accepted_modes


def _part_text_fallback(part: Any) -> str | None:
    if isinstance(part, TextPart):
        return part.text
    if isinstance(part, DataPart):
        return json.dumps(part.data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if isinstance(part, FilePart):
        payload = part.file
        mime_type = _file_payload_value(payload, "mimeType", "mime_type")
        name = _file_payload_value(payload, "name")
        uri = _file_payload_value(payload, "uri")
        details = [value for value in (name, mime_type, uri) if isinstance(value, str) and value]
        if details:
            return f"[file omitted: {' | '.join(details)}]"
        return "[file omitted]"
    return None


def _file_payload_value(payload: Any, *field_names: str) -> Any:
    for field_name in field_names:
        value = getattr(payload, field_name, None)
        if value is not None:
            return value

    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump(by_alias=True, exclude_none=True)
        if isinstance(dumped, dict):
            for field_name in field_names:
                if field_name in dumped:
                    return dumped[field_name]
    return None
