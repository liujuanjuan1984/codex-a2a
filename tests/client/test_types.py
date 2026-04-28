from __future__ import annotations

import pytest
from a2a.types import Message
from pydantic import ValidationError

from codex_a2a.a2a_proto import new_data_part, new_text_part
from codex_a2a.client.types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


def test_send_request_accepts_text_payload() -> None:
    request = A2ASendRequest(
        text="hello world",
        context_id="ctx-1",
        metadata={"lang": "zh"},
        accepted_output_modes=["text/plain"],
        history_length=5,
        blocking=False,
    )

    assert request.text == "hello world"
    assert request.context_id == "ctx-1"
    assert request.metadata == {"lang": "zh"}
    assert request.accepted_output_modes == ["text/plain"]
    assert request.history_length == 5
    assert request.blocking is False


def test_send_request_accepts_parts_payload() -> None:
    request = A2ASendRequest(
        parts=[new_text_part("hello"), new_data_part({"kind": "mention", "path": "/tmp/x"})]
    )

    assert request.parts is not None
    assert len(request.parts) == 2


def test_send_request_accepts_message_payload() -> None:
    message = Message(message_id="msg-1", parts=[new_text_part("hello")])

    request = A2ASendRequest(message=message)

    assert request.message is message


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        ({}, "Exactly one of text, parts, or message must be provided"),
        (
            {"text": "hello", "parts": [new_text_part("world")]},
            "Exactly one of text, parts, or message must be provided",
        ),
        (
            {"parts": []},
            "parts must not be empty",
        ),
        (
            {
                "message": Message(message_id="msg-1", parts=[new_text_part("hello")]),
                "context_id": "ctx-1",
            },
            "context_id, task_id, and message_id cannot be combined with message",
        ),
    ],
)
def test_send_request_rejects_invalid_payload_shapes(
    kwargs: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        A2ASendRequest(**kwargs)


def test_get_task_request_fields() -> None:
    request = A2AGetTaskRequest(task_id="task-1", history_length=10, metadata={"k": "v"})

    assert request.task_id == "task-1"
    assert request.history_length == 10
    assert request.metadata == {"k": "v"}


def test_cancel_task_request_fields() -> None:
    request = A2ACancelTaskRequest(task_id="task-1", metadata={"reason": "manual"})

    assert request.task_id == "task-1"
    assert request.metadata == {"reason": "manual"}
