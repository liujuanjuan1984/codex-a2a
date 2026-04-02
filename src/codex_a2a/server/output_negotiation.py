from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any, cast

from a2a.server.events import EventConsumer
from a2a.server.tasks import ResultAggregator, TaskManager
from a2a.types import (
    Artifact,
    DataPart,
    FilePart,
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)

from codex_a2a.media_modes import (
    APPLICATION_JSON_MEDIA_MODE,
    TEXT_PLAIN_MEDIA_MODE,
)

OUTPUT_NEGOTIATION_METADATA_KEY = "output_negotiation"
OUTPUT_NEGOTIATION_ACCEPTED_OUTPUT_MODES_FIELD = "accepted_output_modes"


def normalize_accepted_output_modes(
    accepted_output_modes: Iterable[str] | None,
) -> frozenset[str] | None:
    if accepted_output_modes is None:
        return None

    normalized = frozenset(
        mode.strip().lower()
        for mode in accepted_output_modes
        if isinstance(mode, str) and mode.strip()
    )
    if not normalized or "*/*" in normalized or "*" in normalized:
        return None
    return normalized


def build_output_negotiation_metadata(
    accepted_output_modes: Iterable[str] | None,
) -> dict[str, Any] | None:
    normalized = normalize_accepted_output_modes(accepted_output_modes)
    if normalized is None:
        return None
    return {
        "codex": {
            OUTPUT_NEGOTIATION_METADATA_KEY: {
                OUTPUT_NEGOTIATION_ACCEPTED_OUTPUT_MODES_FIELD: sorted(normalized),
            }
        }
    }


def merge_output_negotiation_metadata(
    metadata: dict[str, Any] | None,
    accepted_output_modes: Iterable[str] | None,
) -> dict[str, Any] | None:
    negotiation_metadata = build_output_negotiation_metadata(accepted_output_modes)
    if negotiation_metadata is None:
        return metadata

    merged = dict(metadata) if metadata else {}
    codex_metadata = merged.get("codex")
    if not isinstance(codex_metadata, dict):
        codex_metadata = {}
    else:
        codex_metadata = dict(codex_metadata)

    codex_metadata[OUTPUT_NEGOTIATION_METADATA_KEY] = dict(
        cast(dict[str, Any], negotiation_metadata["codex"][OUTPUT_NEGOTIATION_METADATA_KEY])
    )
    merged["codex"] = codex_metadata
    return merged


def extract_accepted_output_modes_from_metadata(
    metadata: dict[str, Any] | None,
) -> frozenset[str] | None:
    if not isinstance(metadata, dict):
        return None
    codex_metadata = metadata.get("codex")
    if not isinstance(codex_metadata, dict):
        return None
    negotiation_metadata = codex_metadata.get(OUTPUT_NEGOTIATION_METADATA_KEY)
    if not isinstance(negotiation_metadata, dict):
        return None
    accepted_output_modes = negotiation_metadata.get(OUTPUT_NEGOTIATION_ACCEPTED_OUTPUT_MODES_FIELD)
    if not isinstance(accepted_output_modes, list):
        return None
    return normalize_accepted_output_modes(accepted_output_modes)


def annotate_output_negotiation_metadata(
    payload: Any,
    accepted_output_modes: Iterable[str] | None,
) -> Any:
    normalized = normalize_accepted_output_modes(accepted_output_modes)
    if normalized is None:
        return payload

    if isinstance(payload, Task):
        return payload.model_copy(
            update={"metadata": merge_output_negotiation_metadata(payload.metadata, normalized)}
        )

    if isinstance(payload, TaskStatusUpdateEvent):
        return payload.model_copy(
            update={"metadata": merge_output_negotiation_metadata(payload.metadata, normalized)}
        )

    if isinstance(payload, TaskArtifactUpdateEvent):
        return payload.model_copy(
            update={"metadata": merge_output_negotiation_metadata(payload.metadata, normalized)}
        )

    return payload


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


class NegotiatingResultAggregator(ResultAggregator):
    def __init__(
        self,
        task_manager: TaskManager,
        accepted_output_modes: Iterable[str] | None,
    ) -> None:
        super().__init__(task_manager)
        self._accepted_output_modes = normalize_accepted_output_modes(accepted_output_modes)

    def _transform_event(self, event: Any) -> Any | None:
        negotiated_event = apply_accepted_output_modes(event, self._accepted_output_modes)
        if negotiated_event is None:
            return None
        return annotate_output_negotiation_metadata(negotiated_event, self._accepted_output_modes)

    async def _persist_output_negotiation_metadata(self, event: Any) -> None:
        if not isinstance(event, TaskArtifactUpdateEvent):
            return

        accepted_output_modes = extract_accepted_output_modes_from_metadata(event.metadata)
        if accepted_output_modes is None:
            return

        task = await self.task_manager.ensure_task(event)
        merged_metadata = merge_output_negotiation_metadata(task.metadata, accepted_output_modes)
        if merged_metadata == task.metadata:
            return
        task.metadata = merged_metadata
        await self.task_manager._save_task(task)

    async def consume_and_emit(self, consumer: EventConsumer):  # noqa: ANN201
        async for event in consumer.consume_all():
            transformed_event = self._transform_event(event)
            if transformed_event is None:
                continue
            await self._persist_output_negotiation_metadata(transformed_event)
            await self.task_manager.process(transformed_event)
            yield transformed_event

    async def consume_all(self, consumer: EventConsumer) -> Task | Message | None:
        async for event in consumer.consume_all():
            transformed_event = self._transform_event(event)
            if transformed_event is None:
                continue
            if isinstance(transformed_event, Message):
                self._message = transformed_event
                return transformed_event
            await self._persist_output_negotiation_metadata(transformed_event)
            await self.task_manager.process(transformed_event)
        return await self.task_manager.get_task()

    async def consume_and_break_on_interrupt(
        self,
        consumer: EventConsumer,
        blocking: bool = True,
        event_callback=None,  # noqa: ANN001
    ) -> tuple[Task | Message | None, bool, asyncio.Task | None]:
        event_stream = consumer.consume_all()
        interrupted = False
        bg_task: asyncio.Task | None = None
        async for event in event_stream:
            transformed_event = self._transform_event(event)
            if transformed_event is None:
                continue
            if isinstance(transformed_event, Message):
                self._message = transformed_event
                return transformed_event, False, None
            await self._persist_output_negotiation_metadata(transformed_event)
            await self.task_manager.process(transformed_event)

            should_interrupt = False
            is_auth_required = (
                isinstance(transformed_event, Task | TaskStatusUpdateEvent)
                and transformed_event.status.state == TaskState.auth_required
            )
            if is_auth_required:
                should_interrupt = True
            elif not blocking:
                should_interrupt = True

            if should_interrupt:
                bg_task = asyncio.create_task(
                    self._continue_consuming(event_stream, event_callback)
                )
                interrupted = True
                break
        return await self.task_manager.get_task(), interrupted, bg_task

    async def _continue_consuming(
        self,
        event_stream,
        event_callback=None,  # noqa: ANN001
    ) -> None:
        async for event in event_stream:
            transformed_event = self._transform_event(event)
            if transformed_event is None:
                continue
            await self._persist_output_negotiation_metadata(transformed_event)
            await self.task_manager.process(transformed_event)
            if event_callback:
                await event_callback()


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
        if media_mode is not None and media_mode_is_accepted(media_mode, accepted_modes):
            filtered_parts.append(part)
            continue

        if media_mode_is_accepted(TEXT_PLAIN_MEDIA_MODE, accepted_modes):
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


def media_mode_is_accepted(media_mode: str, accepted_modes: frozenset[str]) -> bool:
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
