import asyncio
from unittest.mock import AsyncMock

import pytest

from codex_a2a.execution.discovery_runtime import CodexDiscoveryRuntime
from codex_a2a.execution.review_runtime import CodexReviewRuntime
from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from codex_a2a.upstream.client import CodexClient
from tests.execution.test_discovery_exec_runtime import RecordingRequestHandler
from tests.support.context import DummyEventQueue
from tests.support.settings import make_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["discovery", "review", "thread"])
async def test_watch_cancellation_releases_upstream_subscription_during_emit(monkeypatch, kind):
    client = CodexClient(make_settings(a2a_bearer_token="test-token"))
    monkeypatch.setattr(client, "_ensure_started", AsyncMock())
    handler = RecordingRequestHandler(hold_open=True)
    emitting = asyncio.Event()

    class BlockingQueue(DummyEventQueue):
        async def enqueue_event(self, event):
            emitting.set()
            await asyncio.Event().wait()

    if kind == "discovery":
        runtime = CodexDiscoveryRuntime(client=client, request_handler=handler)
        await runtime.start(request={"events": ["skills.changed"]}, context=None)
        event = {"type": "discovery.skills.changed", "properties": {}}
    elif kind == "review":
        runtime = CodexReviewRuntime(client=client, request_handler=handler)
        await runtime.start(
            thread_id="source",
            review_thread_id="review",
            turn_id="turn",
            request={"events": ["review.completed"]},
            context=None,
        )
        event = {
            "type": "turn.lifecycle.completed",
            "properties": {
                "thread_id": "review",
                "turn_id": "turn",
                "turn": {"status": "completed"},
            },
        }
    else:
        runtime = CodexThreadLifecycleRuntime(client=client, request_handler=handler)
        await runtime.start(request={"events": ["thread.started"]}, context=None)
        event = {"type": "thread.lifecycle.started", "properties": {"thread_id": "thread"}}

    producer = asyncio.create_task(handler.saved_producer(BlockingQueue()))
    try:
        await asyncio.sleep(0)
        assert len(client._stream_bridge.event_subscribers) == 1
        await client._stream_bridge.enqueue_stream_event(event)
        await asyncio.wait_for(emitting.wait(), 2)
        producer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await producer
        assert not client._stream_bridge.event_subscribers
    finally:
        if not producer.done():
            producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        await handler.close()
        await client.close()
