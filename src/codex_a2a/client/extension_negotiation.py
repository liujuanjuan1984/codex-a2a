from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.types import (
    Artifact,
    Message,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
)
from google.protobuf.message import Message as ProtoMessage  # type: ignore[import-untyped]

from codex_a2a.a2a_proto import proto_clone, proto_to_python
from codex_a2a.contracts import extensions as extension_contracts

_STREAMING_SHARED_METADATA_KEYS = frozenset({"stream", "progress", "interrupt", "usage"})


@dataclass(frozen=True)
class ExtensionRequirement:
    extension_uri: str
    field: str


def merge_extension_service_parameters(
    service_parameters: Mapping[str, str] | None,
    extensions: Sequence[str] | None,
) -> dict[str, str] | None:
    normalized_extensions = [
        value for value in list(extensions or []) if isinstance(value, str) and value
    ]
    base = dict(service_parameters or {})
    if not base and not normalized_extensions:
        return None
    updates = [with_a2a_extensions(normalized_extensions)] if normalized_extensions else []
    merged = ServiceParametersFactory.create_from(base or None, updates)
    return merged or None


def parse_requested_extensions(values: Sequence[str]) -> tuple[str, ...] | None:
    requested: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        for item in value.split(","):
            normalized = item.strip()
            if normalized and normalized not in requested:
                requested.append(normalized)
    return tuple(requested) or None


def merge_requested_extensions(
    explicit_extensions: Sequence[str] | None,
    metadata_extensions: Sequence[str] | None,
) -> tuple[str, ...] | None:
    merged: list[str] = []
    for value in list(explicit_extensions or ()) + list(metadata_extensions or ()):
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return tuple(merged) or None


def required_extensions_for_send_message(
    *,
    request_metadata: Mapping[str, Any] | None,
    message: Message,
) -> tuple[ExtensionRequirement, ...]:
    sources: list[Mapping[str, Any]] = []
    if request_metadata:
        sources.append(dict(request_metadata))
    message_metadata = _proto_metadata_to_dict(
        message.metadata if message.HasField("metadata") else None
    )
    if message_metadata:
        sources.append(message_metadata)
    requirements: list[ExtensionRequirement] = []
    for source in sources:
        current: Any = source
        for segment in ("shared", "session", "id"):
            if not isinstance(current, Mapping) or segment not in current:
                current = None
                break
            current = current[segment]
        if current is not None:
            requirements.append(
                ExtensionRequirement(
                    extension_uri=extension_contracts.SESSION_BINDING_EXTENSION_URI,
                    field="metadata.shared.session.id",
                )
            )
            break
    return tuple(requirements)


def missing_extension_requirements(
    requirements: Sequence[ExtensionRequirement],
    requested_extensions: Iterable[str] | None,
) -> tuple[ExtensionRequirement, ...]:
    requested = {
        value.strip()
        for value in list(requested_extensions or ())
        if isinstance(value, str) and value.strip()
    }
    missing = [
        requirement for requirement in requirements if requirement.extension_uri not in requested
    ]
    return tuple(missing)


def filter_negotiated_extensions_from_stream_response(
    event: StreamResponse,
    requested_extensions: Iterable[str] | None,
) -> StreamResponse:
    requested = _normalize_requested_extensions(requested_extensions)
    if not requested:
        requested = frozenset()

    updated = cast(StreamResponse, proto_clone(event))
    if updated.HasField("message"):
        _set_filtered_metadata(updated.message, requested)
    if updated.HasField("task"):
        updated.task.CopyFrom(_filter_task(updated.task, requested))
    if updated.HasField("status_update"):
        status_update = cast(TaskStatusUpdateEvent, proto_clone(updated.status_update))
        _set_filtered_metadata(status_update, requested)
        if status_update.status.HasField("message"):
            _set_filtered_metadata(status_update.status.message, requested)
        updated.status_update.CopyFrom(status_update)
    if updated.HasField("artifact_update"):
        artifact_update = cast(TaskArtifactUpdateEvent, proto_clone(updated.artifact_update))
        _set_filtered_metadata(artifact_update.artifact, requested)
        updated.artifact_update.CopyFrom(artifact_update)
    return updated


def filter_negotiated_extensions_from_task(
    task: Task,
    requested_extensions: Iterable[str] | None,
) -> Task:
    return _filter_task(task, _normalize_requested_extensions(requested_extensions))


def _normalize_requested_extensions(
    requested_extensions: Iterable[str] | None,
) -> frozenset[str]:
    return frozenset(
        value.strip()
        for value in list(requested_extensions or ())
        if isinstance(value, str) and value.strip()
    )


def _filter_task(task: Task, requested_extensions: frozenset[str]) -> Task:
    updated = cast(Task, proto_clone(task))
    _set_filtered_metadata(updated, requested_extensions)
    if updated.status.HasField("message"):
        _set_filtered_metadata(updated.status.message, requested_extensions)
    for history_item in updated.history:
        _set_filtered_metadata(history_item, requested_extensions)
    for artifact in updated.artifacts:
        _set_filtered_metadata(artifact, requested_extensions)
    return updated


def _set_filtered_metadata(
    proto: Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent | Artifact | Message,
    requested_extensions: frozenset[str],
) -> None:
    metadata_dict = _proto_metadata_to_dict(getattr(proto, "metadata", None))
    filtered_metadata = _filter_metadata_dict(metadata_dict, requested_extensions)
    proto.ClearField("metadata")
    if filtered_metadata:
        proto.metadata.update(filtered_metadata)


def _proto_metadata_to_dict(metadata: ProtoMessage | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    normalized = proto_to_python(metadata)
    if isinstance(normalized, dict):
        return normalized or None
    return None


def _filter_metadata_dict(
    metadata: Mapping[str, Any] | None,
    requested_extensions: frozenset[str],
) -> dict[str, Any] | None:
    if not metadata:
        return None
    normalized = dict(metadata)
    shared_metadata = normalized.get("shared")
    if isinstance(shared_metadata, Mapping):
        filtered_shared = dict(shared_metadata)
        if (
            extension_contracts.SESSION_BINDING_EXTENSION_URI not in requested_extensions
            and extension_contracts.STREAMING_EXTENSION_URI not in requested_extensions
        ):
            filtered_shared.pop("session", None)
        if extension_contracts.STREAMING_EXTENSION_URI not in requested_extensions:
            for key in _STREAMING_SHARED_METADATA_KEYS:
                filtered_shared.pop(key, None)
        if filtered_shared:
            normalized["shared"] = filtered_shared
        else:
            normalized.pop("shared", None)
    return normalized or None
