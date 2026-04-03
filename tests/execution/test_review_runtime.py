from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types import TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from codex_a2a.execution.review_runtime import CodexReviewRuntime
from tests.execution.test_discovery_exec_runtime import RecordingRequestHandler
from tests.support.context import DummyEventQueue


def _artifact_updates(queue: DummyEventQueue) -> list[TaskArtifactUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]


def _status_updates(queue: DummyEventQueue) -> list[TaskStatusUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]


def _part_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    part = event.artifact.parts[0]
    data = getattr(part, "data", None) or getattr(getattr(part, "root", None), "data", None)
    return data if isinstance(data, dict) else {}


class ReviewClientStub:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def stream_events(  # noqa: ANN201
        self,
        stop_event=None,  # noqa: ANN001
        *,
        directory: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        del directory
        for event in self._events:
            if stop_event is not None and stop_event.is_set():
                break
            yield event


@pytest.mark.asyncio
async def test_review_runtime_start_bridges_lifecycle_notifications() -> None:
    request_handler = RecordingRequestHandler()
    client = ReviewClientStub(
        [
            {
                "type": "thread.lifecycle.status_changed",
                "properties": {
                    "thread_id": "thr-1-review",
                    "status": {"type": "running"},
                    "source": "thread/status/changed",
                    "codex": {"raw": {"threadId": "thr-1-review", "status": "running"}},
                },
            },
            {
                "type": "turn.lifecycle.completed",
                "properties": {
                    "thread_id": "thr-1-review",
                    "turn_id": "turn-review-1",
                    "turn": {
                        "id": "turn-review-1",
                        "status": "completed",
                        "items": [],
                    },
                    "status": "completed",
                    "source": "turn/completed",
                    "codex": {"raw": {"threadId": "thr-1-review"}},
                },
            },
        ]
    )
    runtime = CodexReviewRuntime(client=client, request_handler=request_handler)

    result = await runtime.start(
        thread_id="thr-1",
        review_thread_id="thr-1-review",
        turn_id="turn-review-1",
        request={"events": ["review.started", "review.status.changed", "review.completed"]},
        context={"identity": "demo"},
    )

    assert result["ok"] is True
    assert request_handler.saved_task is not None
    assert request_handler.saved_task.metadata == {
        "codex": {
            "review_watch": {
                "thread_id": "thr-1",
                "review_thread_id": "thr-1-review",
                "turn_id": "turn-review-1",
                "events": ["review.completed", "review.started", "review.status.changed"],
            }
        }
    }
    assert request_handler.saved_context == {"identity": "demo"}

    queue = DummyEventQueue()
    await request_handler.saved_producer(queue)

    artifacts = _artifact_updates(queue)
    assert [_part_data(event)["kind"] for event in artifacts] == [
        "review_started",
        "review_status_changed",
        "review_completed",
    ]
    assert _part_data(artifacts[0])["source"] == "review/start"
    assert _part_data(artifacts[1])["status"] == {"type": "running"}
    assert _part_data(artifacts[2])["review"]["id"] == "turn-review-1"
    assert artifacts[0].append is False
    assert artifacts[-1].last_chunk is True

    statuses = _status_updates(queue)
    assert len(statuses) == 1
    assert statuses[0].status.state == TaskState.completed
    assert statuses[0].final is True


@pytest.mark.asyncio
async def test_review_runtime_maps_failed_turns_to_failed_terminal_status() -> None:
    request_handler = RecordingRequestHandler()
    client = ReviewClientStub(
        [
            {
                "type": "turn.lifecycle.completed",
                "properties": {
                    "thread_id": "thr-1",
                    "turn_id": "turn-review-1",
                    "turn": {
                        "id": "turn-review-1",
                        "status": "failed",
                        "error": {"message": "boom"},
                    },
                    "status": "failed",
                    "source": "turn/completed",
                },
            },
        ]
    )
    runtime = CodexReviewRuntime(client=client, request_handler=request_handler)

    await runtime.start(
        thread_id="thr-1",
        review_thread_id="thr-1",
        turn_id="turn-review-1",
        request={"events": ["review.started", "review.failed"]},
        context=None,
    )

    queue = DummyEventQueue()
    await request_handler.saved_producer(queue)

    artifacts = _artifact_updates(queue)
    assert [_part_data(event)["kind"] for event in artifacts] == [
        "review_started",
        "review_failed",
    ]
    statuses = _status_updates(queue)
    assert len(statuses) == 1
    assert statuses[0].status.state == TaskState.failed
    assert statuses[0].final is True


@pytest.mark.asyncio
async def test_review_runtime_rejects_invalid_event_filters() -> None:
    runtime = CodexReviewRuntime(
        client=ReviewClientStub([]),
        request_handler=RecordingRequestHandler(),
    )

    with pytest.raises(ValueError, match="request.events entries must be one of"):
        await runtime.start(
            thread_id="thr-1",
            review_thread_id="thr-1-review",
            turn_id="turn-review-1",
            request={"events": ["review.delta"]},
            context=None,
        )
