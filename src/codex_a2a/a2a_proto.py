from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict  # type: ignore[import-untyped]
from google.protobuf.message import Message as ProtoMessage  # type: ignore[import-untyped]
from google.protobuf.struct_pb2 import Struct, Value  # type: ignore[import-untyped]

from a2a.types import Part, Role, TaskState

ROLE_AGENT = Role.ROLE_AGENT
ROLE_USER = Role.ROLE_USER

TASK_STATE_SUBMITTED = TaskState.TASK_STATE_SUBMITTED
TASK_STATE_WORKING = TaskState.TASK_STATE_WORKING
TASK_STATE_COMPLETED = TaskState.TASK_STATE_COMPLETED
TASK_STATE_FAILED = TaskState.TASK_STATE_FAILED
TASK_STATE_CANCELED = TaskState.TASK_STATE_CANCELED
TASK_STATE_INPUT_REQUIRED = TaskState.TASK_STATE_INPUT_REQUIRED
TASK_STATE_REJECTED = TaskState.TASK_STATE_REJECTED
TASK_STATE_AUTH_REQUIRED = TaskState.TASK_STATE_AUTH_REQUIRED


def to_value(value: Any) -> Value:
    return ParseDict(value, Value())


def to_struct(value: Mapping[str, Any] | None) -> Struct | None:
    if value is None:
        return None
    struct_value = Struct()
    struct_value.update(dict(value))
    return struct_value


def proto_to_python(value: Any) -> Any:
    if isinstance(value, ProtoMessage):
        return MessageToDict(value, preserving_proto_field_name=True)
    if isinstance(value, Mapping):
        return {str(key): proto_to_python(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [proto_to_python(item) for item in value]
    if isinstance(value, Iterable) and not isinstance(value, str | bytes | bytearray):
        return [proto_to_python(item) for item in value]
    return value


def proto_clone(message: ProtoMessage) -> ProtoMessage:
    clone = type(message)()
    clone.CopyFrom(message)
    return clone


def proto_with_updates(proto_message: ProtoMessage, **updates: Any) -> ProtoMessage:
    payload = proto_to_python(proto_message)
    if not isinstance(payload, dict):
        raise TypeError("Expected protobuf message to serialize as object")
    payload.update({key: _normalize_for_proto_parse(value) for key, value in updates.items()})
    clone = type(proto_message)()
    ParseDict(payload, clone)
    return clone


def new_text_part(text: str) -> Part:
    return Part(text=text)


def new_data_part(data: Any) -> Part:
    return Part(data=to_value(data))


def new_file_url_part(
    url: str,
    *,
    media_type: str | None = None,
    filename: str | None = None,
) -> Part:
    kwargs: dict[str, Any] = {"url": url}
    if media_type is not None:
        kwargs["media_type"] = media_type
    if filename is not None:
        kwargs["filename"] = filename
    return Part(**kwargs)


def new_file_bytes_part(
    raw: bytes,
    *,
    media_type: str | None = None,
    filename: str | None = None,
) -> Part:
    kwargs: dict[str, Any] = {"raw": raw}
    if media_type is not None:
        kwargs["media_type"] = media_type
    if filename is not None:
        kwargs["filename"] = filename
    return Part(**kwargs)


def part_kind(part: Part | None) -> str | None:
    if part is None:
        return None
    return part.WhichOneof("content")


def is_text_part(part: Part | None) -> bool:
    return part_kind(part) == "text"


def is_data_part(part: Part | None) -> bool:
    return part_kind(part) == "data"


def is_file_part(part: Part | None) -> bool:
    return part_kind(part) in {"raw", "url"}


def part_text(part: Part | None) -> str | None:
    if not is_text_part(part):
        return None
    assert part is not None
    return part.text


def part_data(part: Part | None) -> Any:
    if not is_data_part(part):
        return None
    assert part is not None
    return proto_to_python(part.data)


def _normalize_for_proto_parse(value: Any) -> Any:
    if isinstance(value, ProtoMessage):
        return proto_to_python(value)
    if isinstance(value, list):
        return [_normalize_for_proto_parse(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_for_proto_parse(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_for_proto_parse(item) for key, item in value.items()}
    return value
