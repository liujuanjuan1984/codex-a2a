from __future__ import annotations

import uuid

from a2a.types import (
    Message,
    MessageSendConfiguration,
    Part,
    Role,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TextPart,
)
from pydantic import BaseModel, Field


class A2ASendRequest(BaseModel):
    """User-facing input for a message send operation."""

    text: str
    context_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, object] | None = None
    accepted_output_modes: list[str] | None = None
    history_length: int | None = None
    blocking: bool = True

    def to_message(self) -> Message:
        return Message(
            message_id=self.message_id or f"msg-{uuid.uuid4().hex[:12]}",
            role=Role.user,
            context_id=self.context_id,
            metadata=self.metadata,
            parts=[Part(root=TextPart(text=self.text))],
        )

    def to_send_configuration(self) -> MessageSendConfiguration:
        config_kwargs: dict[str, object] = {"blocking": self.blocking}
        if self.accepted_output_modes is not None:
            config_kwargs["acceptedOutputModes"] = self.accepted_output_modes
        if self.history_length is not None:
            config_kwargs["historyLength"] = self.history_length
        return MessageSendConfiguration(**config_kwargs)


class A2AGetTaskRequest(BaseModel):
    """User-facing input for task query."""

    task_id: str
    history_length: int | None = None
    metadata: dict[str, object] | None = None

    def to_task_query(self) -> TaskQueryParams:
        return TaskQueryParams(
            id=self.task_id,
            historyLength=self.history_length,
            metadata=self.metadata,
        )


class A2ACancelTaskRequest(BaseModel):
    """User-facing input for canceling a task."""

    task_id: str = Field(min_length=1)
    metadata: dict[str, object] | None = None

    def to_task_id(self) -> TaskIdParams:
        return TaskIdParams(id=self.task_id, metadata=self.metadata)


class A2ASendResult(BaseModel):
    """Normalized payload from a send request."""

    final: Task | Message | None = None
