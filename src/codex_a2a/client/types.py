from __future__ import annotations

from a2a.types import Message, Part
from pydantic import BaseModel, ConfigDict, Field, model_validator


class A2ASendRequest(BaseModel):
    """User-facing input for a message send operation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str | None = None
    parts: list[Part] | None = None
    message: Message | None = None
    context_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, object] | None = None
    accepted_output_modes: list[str] | None = None
    history_length: int | None = None
    blocking: bool = True

    @model_validator(mode="after")
    def validate_payload_shape(self) -> A2ASendRequest:
        payload_count = sum(
            value is not None
            for value in (
                self.text,
                self.parts,
                self.message,
            )
        )
        if payload_count != 1:
            raise ValueError("Exactly one of text, parts, or message must be provided")

        if self.parts is not None and not self.parts:
            raise ValueError("parts must not be empty")

        if self.message is not None and any(
            value is not None
            for value in (
                self.context_id,
                self.task_id,
                self.message_id,
            )
        ):
            raise ValueError("context_id, task_id, and message_id cannot be combined with message")

        return self


class A2AGetTaskRequest(BaseModel):
    """User-facing input for task query."""

    task_id: str
    history_length: int | None = None
    metadata: dict[str, object] | None = None


class A2ACancelTaskRequest(BaseModel):
    """User-facing input for canceling a task."""

    task_id: str = Field(min_length=1)
    metadata: dict[str, object] | None = None
