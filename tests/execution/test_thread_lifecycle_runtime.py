from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types import TaskArtifactUpdateEvent

from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from tests.execution.test_discovery_exec_runtime import RecordingRequestHandler
from tests.support.context import DummyEventQueue


def _artifact_updates(queue: DummyEventQueue) -> list[TaskArtifactUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]


def _part_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    part = event.artifact.parts[0]
    data = getattr(part, "data", None) or getattr(getattr(part, "root", None), "data", None)
    return data if isinstance(data, dict) else {}


class ThreadLifecycleClientStub:
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
async def test_thread_lifecycle_runtime_start_bridges_supported_notifications() -> None:
    request_handler = RecordingRequestHandler()
    client = ThreadLifecycleClientStub(
        [
            {
                "type": "thread.lifecycle.started",
                "properties": {
                    "thread_id": "thr-1",
                    "status": {"type": "idle"},
                    "thread": {"id": "thr-1", "title": "Thread 1"},
                    "source": "thread/started",
                    "codex": {"raw": {"threadId": "thr-1"}},
                },
            },
            {
                "type": "thread.lifecycle.status_changed",
                "properties": {
                    "thread_id": "thr-1",
                    "status": {"type": "running"},
                    "source": "thread/status/changed",
                    "codex": {"raw": {"threadId": "thr-1", "status": "running"}},
                },
            },
            {
                "type": "thread.lifecycle.archived",
                "properties": {
                    "thread_id": "thr-2",
                    "source": "thread/archived",
                    "codex": {"raw": {"threadId": "thr-2"}},
                },
            },
        ]
    )
    runtime = CodexThreadLifecycleRuntime(client=client, request_handler=request_handler)

    result = await runtime.start(
        request={
            "events": ["thread.started", "thread.status.changed"],
            "threadIds": ["thr-1"],
        },
        context={"identity": "demo"},
    )

    assert result["ok"] is True
    assert request_handler.saved_task is not None
    assert request_handler.saved_task.metadata == {
        "codex": {
            "thread_lifecycle_watch": {
                "events": ["thread.started", "thread.status.changed"],
                "thread_ids": ["thr-1"],
            }
        }
    }
    assert request_handler.saved_context == {"identity": "demo"}

    queue = DummyEventQueue()
    await request_handler.saved_producer(queue)

    artifacts = _artifact_updates(queue)
    assert [_part_data(event)["kind"] for event in artifacts] == [
        "thread_started",
        "thread_status_changed",
    ]
    assert _part_data(artifacts[0])["thread"]["title"] == "Thread 1"
    assert _part_data(artifacts[1])["status"] == {"type": "running"}
    assert artifacts[0].append is False
    assert artifacts[1].append is True


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_rejects_invalid_event_filters() -> None:
    runtime = CodexThreadLifecycleRuntime(
        client=ThreadLifecycleClientStub([]),
        request_handler=RecordingRequestHandler(),
    )

    with pytest.raises(ValueError, match="request.events entries must be one of"):
        await runtime.start(request={"events": ["thread.deleted"]}, context=None)
