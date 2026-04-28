from __future__ import annotations

from a2a.types import (
    Artifact,
    Message,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
)

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.client.payload_text import extract_text_from_payload


def test_extract_text_from_payload_prefers_stream_artifact_update() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )
    update = TaskArtifactUpdateEvent(
        task_id="remote-task",
        context_id="remote-context",
        artifact=Artifact(
            artifact_id="artifact-1",
            name="response",
            parts=[new_text_part("streamed remote text")],
        ),
    )

    assert extract_text_from_payload(StreamResponse(task=task)) is None
    assert (
        extract_text_from_payload(StreamResponse(artifact_update=update)) == "streamed remote text"
    )


def test_extract_text_from_payload_reads_status_message() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(
            state=TaskState.TASK_STATE_COMPLETED,
            message=Message(
                role=Role.ROLE_AGENT,
                message_id="m1",
                parts=[new_text_part("status message text")],
            ),
        ),
    )

    assert extract_text_from_payload(task) == "status message text"


def test_extract_text_from_payload_reads_stream_message() -> None:
    response = StreamResponse(
        message=Message(
            role=Role.ROLE_AGENT,
            message_id="m2",
            parts=[new_text_part("stream message text")],
        )
    )

    assert extract_text_from_payload(response) == "stream message text"
