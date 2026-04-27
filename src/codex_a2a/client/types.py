from __future__ import annotations

import uuid

from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Role,
    SendMessageConfiguration,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
)
from pydantic import BaseModel, Field

from codex_a2a.a2a_proto import new_text_part, to_struct


class A2ASendRequest(BaseModel):
    """User-facing input for a message send operation."""

    text: str
    context_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, object] | None = None
    accepted_output_modes: list[str] | None = None
    history_length: int | None = None
    blocking: bool = True

    def to_message(self) -> Message:
        return Message(
            message_id=self.message_id or f"msg-{uuid.uuid4().hex[:12]}",
            role=Role.ROLE_USER,
            context_id=self.context_id,
            metadata=self.metadata,
            parts=[new_text_part(self.text)],
        )

    def to_send_configuration(self) -> SendMessageConfiguration:
        return SendMessageConfiguration(
            return_immediately=not self.blocking,
            accepted_output_modes=self.accepted_output_modes,
            history_length=self.history_length,
        )


class A2AGetTaskRequest(BaseModel):
    """User-facing input for task query."""

    task_id: str
    history_length: int | None = None
    metadata: dict[str, object] | None = None

    def to_task_query(self) -> GetTaskRequest:
        return GetTaskRequest(
            id=self.task_id,
            history_length=self.history_length,
        )


class A2ACancelTaskRequest(BaseModel):
    """User-facing input for canceling a task."""

    task_id: str = Field(min_length=1)
    metadata: dict[str, object] | None = None

    def to_task_id(self) -> CancelTaskRequest:
        request = CancelTaskRequest(id=self.task_id)
        metadata = to_struct(self.metadata)
        if metadata is not None:
            request.metadata.CopyFrom(metadata)
        return request


A2AClientEvent = (
    StreamResponse
    | Task
    | Message
    | tuple[Task, TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None]
)
