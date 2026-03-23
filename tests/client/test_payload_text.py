from __future__ import annotations

from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TextPart,
)

from codex_a2a.client.payload_text import extract_text_from_payload


def test_extract_text_from_payload_prefers_stream_artifact_update() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(state=TaskState.working),
    )
    update = TaskArtifactUpdateEvent(
        task_id="remote-task",
        context_id="remote-context",
        artifact=Artifact(
            artifact_id="artifact-1",
            name="response",
            parts=[Part(root=TextPart(text="streamed remote text"))],
        ),
    )

    assert extract_text_from_payload((task, update)) == "streamed remote text"


def test_extract_text_from_payload_reads_status_message() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(
            state=TaskState.completed,
            message=Message(
                role=Role.agent,
                message_id="m1",
                parts=[Part(root=TextPart(text="status message text"))],
            ),
        ),
    )

    assert extract_text_from_payload(task) == "status message text"


def test_extract_text_from_payload_reads_nested_mapping_history() -> None:
    payload = {
        "result": {
            "history": [
                {"parts": [{"text": "mapped nested text"}]},
            ]
        }
    }

    assert extract_text_from_payload(payload) == "mapped nested text"


def test_extract_text_from_payload_reads_model_dump_payload() -> None:
    class _Payload:
        def model_dump(self) -> dict[str, object]:
            return {"artifacts": [{"parts": [{"text": "model dump text"}]}]}

    assert extract_text_from_payload(_Payload()) == "model dump text"
