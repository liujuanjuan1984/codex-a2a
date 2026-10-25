"""Offline acceptance checks for SDK lifecycle upgrades; no live service required."""

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from a2a.server.agent_execution import SimpleRequestContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import QueueShutDown
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    Artifact,
    GetTaskRequest,
    Message,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import UnsupportedOperationError

from codex_a2a.a2a_proto import new_text_part, part_text
from codex_a2a.logging_context import bind_correlation_id, get_correlation_id
from codex_a2a.server.agent_card import build_agent_card
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.task_store import build_task_store_runtime, task_store_save
from tests.support.settings import make_settings

pytestmark = pytest.mark.filterwarnings("error::DeprecationWarning")


def _handler(store, *, event_stream=None):
    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=RuntimeError("early failure"))
    return CodexRequestHandler(
        agent_executor=executor,
        task_store=store,
        agent_card=build_agent_card(make_settings(a2a_bearer_token="test-token")),
        event_stream=event_stream,
    )


def _request_handler(executor) -> CodexRequestHandler:
    return CodexRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=build_agent_card(make_settings(a2a_bearer_token="test-token")),
    )


async def _wait_for_active_tasks_to_release(handler: CodexRequestHandler) -> None:
    for _ in range(100):
        if not handler._active_task_registry._active_tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("active tasks were not released")


class _MessageOnlyExecutor:
    async def execute(self, context, event_queue) -> None:  # noqa: ANN001
        await event_queue.enqueue_event(
            Message(
                message_id="direct-response",
                context_id=context.context_id,
                role=Role.ROLE_AGENT,
                parts=[new_text_part("direct response")],
            )
        )

    async def cancel(self, context, event_queue) -> None:  # noqa: ANN001
        del context, event_queue


class _InputRequiredThenCompleteExecutor:
    def __init__(self) -> None:
        self.seen_correlation_ids: list[str | None] = []
        self.task: Task | None = None

    async def execute(self, context, event_queue) -> None:  # noqa: ANN001
        self.seen_correlation_ids.append(get_correlation_id())
        if context.current_task is not None:
            updater = TaskUpdater(event_queue, context.task_id, context.context_id)
            await updater.complete()
            return
        self.task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[context.message],
        )
        await event_queue.enqueue_event(self.task)
        updater = TaskUpdater(event_queue, self.task.id, self.task.context_id)
        await updater.update_status(
            TaskState.TASK_STATE_INPUT_REQUIRED,
            message=updater.new_agent_message([new_text_part("more input required")]),
        )

    async def cancel(self, context, event_queue) -> None:  # noqa: ANN001
        del context, event_queue


def _task():
    return Task(
        id="task",
        context_id="context",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )


def test_handler_uses_public_request_context_builder_seam() -> None:
    assert CodexRequestHandler._setup_active_task is DefaultRequestHandler._setup_active_task


def test_handler_accepts_positional_request_context_builder() -> None:
    builder = SimpleRequestContextBuilder(
        should_populate_referred_tasks=False,
        task_store=None,
    )

    handler = CodexRequestHandler(
        MagicMock(),
        InMemoryTaskStore(),
        build_agent_card(make_settings(a2a_bearer_token="test-token")),
        None,
        None,
        None,
        builder,
    )

    assert handler._request_context_builder._inner is builder


def _status(state):
    return TaskStatusUpdateEvent(
        task_id="task", context_id="context", status=TaskStatus(state=state)
    )


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def runtime(request, tmp_path):
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=(
            f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}" if request.param == "sqlite" else None
        ),
    )
    store = build_task_store_runtime(settings)
    await store.startup()
    handler = _handler(store.task_store, event_stream=store.event_stream)
    try:
        yield handler, store, settings
    finally:
        await handler.aclose()
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("restart_streaming", [False, True])
async def test_early_failure_persists_once_and_terminal_task_cannot_restart(
    runtime, streaming, restart_streaming
):
    handler, _, _ = runtime
    params = SendMessageRequest(
        message=Message(
            message_id="message",
            context_id="context",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        )
    )
    with pytest.raises(RuntimeError, match="early failure"):
        async with asyncio.timeout(2):
            if streaming:
                async for _ in handler.on_message_send_stream(params):
                    pass
            else:
                await handler.on_message_send(params)
    task_id = handler.agent_executor.execute.call_args.args[0].task_id
    snapshot = await handler.on_get_task(GetTaskRequest(id=task_id))
    assert snapshot.status.state == TaskState.TASK_STATE_FAILED
    assert [message.message_id for message in snapshot.history] == ["message"]
    params.message.task_id = task_id
    with pytest.raises(UnsupportedOperationError) as exc_info:
        if restart_streaming:
            async for _ in handler.on_message_send_stream(params):
                pass
        else:
            await handler.on_message_send(params)
    assert exc_info.value.message
    handler.agent_executor.execute.assert_awaited_once()
    assert [
        event async for event in handler.on_subscribe_to_task(SubscribeToTaskRequest(id=task_id))
    ] == [snapshot]
    assert await handler.on_get_task(GetTaskRequest(id=task_id)) == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_direct_message_response_releases_active_task(streaming):
    handler = _request_handler(_MessageOnlyExecutor())
    params = SendMessageRequest(
        message=Message(
            message_id="message",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        )
    )
    try:
        if streaming:
            events = [event async for event in handler.on_message_send_stream(params)]
            assert len(events) == 1
            assert isinstance(events[0], Message)
        else:
            result = await handler.on_message_send(params)
            assert isinstance(result, Message)
        await _wait_for_active_tasks_to_release(handler)
    finally:
        await handler.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_follow_up_message_uses_sender_contextvars(streaming):
    executor = _InputRequiredThenCompleteExecutor()
    handler = _request_handler(executor)
    first_params = SendMessageRequest(
        message=Message(
            message_id="first",
            role=Role.ROLE_USER,
            parts=[new_text_part("first")],
        )
    )

    async def send(params):
        if streaming:
            async for _ in handler.on_message_send_stream(params):
                pass
            assert executor.task is not None
            task = await handler.on_get_task(GetTaskRequest(id=executor.task.id))
            assert task is not None
            return task
        result = await handler.on_message_send(params)
        assert isinstance(result, Task)
        return result

    try:
        with bind_correlation_id("correlation-first"):
            first = await send(first_params)
        assert isinstance(first, Task)
        assert first.status.state == TaskState.TASK_STATE_INPUT_REQUIRED

        second_params = SendMessageRequest(
            message=Message(
                message_id="second",
                task_id=first.id,
                context_id=first.context_id,
                role=Role.ROLE_USER,
                parts=[new_text_part("second")],
            )
        )
        with bind_correlation_id("correlation-second"):
            second = await send(second_params)
        assert isinstance(second, Task)
        assert second.status.state == TaskState.TASK_STATE_COMPLETED
        assert executor.seen_correlation_ids == [
            "correlation-first",
            "correlation-second",
        ]
    finally:
        await handler.aclose()


@pytest.mark.asyncio
async def test_existing_database_snapshot_survives_reopen_without_migration(tmp_path):
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}",
    )
    snapshot = _task()
    snapshot.status.state = TaskState.TASK_STATE_COMPLETED
    snapshot.history.append(Message(message_id="existing", role=Role.ROLE_USER))
    # Generated by the pre-upgrade main revision, not by the code under test.
    fixture = Path(__file__).parents[1] / "fixtures" / "sdk_task_store_main_0a3fb68.sql"
    with sqlite3.connect(tmp_path / "existing.db") as connection:
        connection.executescript(fixture.read_text())

    new_store = build_task_store_runtime(settings)
    await new_store.startup()
    handler = _handler(new_store.task_store, event_stream=new_store.event_stream)
    try:
        assert await handler.on_get_task(GetTaskRequest(id="task")) == snapshot
        assert [
            event async for event in handler.on_subscribe_to_task(SubscribeToTaskRequest(id="task"))
        ] == [snapshot]
    finally:
        await handler.aclose()
        await new_store.shutdown()


@pytest.mark.asyncio
async def test_multiple_subscribers_do_not_duplicate_persistence(runtime, monkeypatch):
    handler, store, _ = runtime
    subscribed = asyncio.Event()
    release = asyncio.Event()
    writes = AsyncMock(wraps=store.task_store.save)
    monkeypatch.setattr(store.task_store, "save", writes)

    async def producer(queue):
        await release.wait()
        for i, text in enumerate(["first", "second"]):
            await queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id="task",
                    context_id="context",
                    artifact=Artifact(artifact_id="artifact", parts=[new_text_part(text)]),
                    append=bool(i),
                )
            )
        await queue.enqueue_event(_status(TaskState.TASK_STATE_COMPLETED))

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    source = await handler._queue_manager.get("task")
    original_tap = source.tap
    taps = []

    async def tap(**kwargs):
        sink = await original_tap(**kwargs)
        taps.append(sink)
        if len(taps) == 2:
            subscribed.set()
        return sink

    monkeypatch.setattr(source, "tap", tap)

    async def consume():
        return [
            event async for event in handler.on_subscribe_to_task(SubscribeToTaskRequest(id="task"))
        ]

    readers = [asyncio.create_task(consume()) for _ in range(2)]
    try:
        await asyncio.wait_for(subscribed.wait(), 2)
        release.set()
        first, second = await asyncio.wait_for(asyncio.gather(*readers), 3)
        await asyncio.wait_for(stream, 2)
        assert first == second
        assert len(first) == 3
        assert first[-1].status.state == TaskState.TASK_STATE_COMPLETED
        assert writes.await_count == 4  # Initial task, two chunks, final status.
        task = await handler.on_get_task(GetTaskRequest(id="task"))
        assert [part_text(part) for part in task.artifacts[0].parts] == ["first", "second"]
        assert all(sink.is_closed() for sink in taps)
    finally:
        release.set()
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("complete_first", [False, True])
async def test_background_failure_preserves_terminal_state(runtime, complete_first):
    handler, _, _ = runtime

    async def producer(queue):
        if complete_first:
            await queue.enqueue_event(_status(TaskState.TASK_STATE_COMPLETED))
        raise RuntimeError("background failed")

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    with pytest.raises(RuntimeError, match="background failed"):
        await stream
    task = await handler.on_get_task(GetTaskRequest(id="task"))
    expected = TaskState.TASK_STATE_COMPLETED if complete_first else TaskState.TASK_STATE_FAILED
    assert task.status.state == expected


@pytest.mark.asyncio
async def test_no_subscribers_does_not_stall_large_background_stream():
    from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore

    handler = _handler(InMemoryTaskStore())

    async def producer(queue):
        for _ in range(2048):
            await queue.enqueue_event(_status(TaskState.TASK_STATE_WORKING))
        await queue.enqueue_event(_status(TaskState.TASK_STATE_COMPLETED))

    try:
        stream = await handler.start_background_task_stream(task=_task(), producer=producer)
        await asyncio.wait_for(stream, 5)
        assert (await handler.on_get_task(GetTaskRequest(id="task"))).status.state == (
            TaskState.TASK_STATE_COMPLETED
        )
    finally:
        await handler.aclose()


@pytest.mark.asyncio
async def test_slow_subscriber_is_evicted_without_blocking_healthy_reader(runtime):
    handler, _, _ = runtime
    source = await handler._queue_manager.create("task")
    slow = await source.tap(max_queue_size=1, evict_on_full=True)
    healthy = await source.tap(max_queue_size=8, evict_on_full=True)
    event = _status(TaskState.TASK_STATE_WORKING)
    for _ in range(4):
        await source.enqueue_event(event)
        assert await asyncio.wait_for(healthy.dequeue_event(), 2) == event
        healthy.task_done()
    assert slow.is_closed()
    with pytest.raises(QueueShutDown):
        await slow.dequeue_event()
    await healthy.close(immediate=True)


@pytest.mark.asyncio
async def test_abandoned_sink_cannot_block_producer_completion(runtime, monkeypatch):
    import codex_a2a.server.request_handler as handler_module

    handler, _, _ = runtime
    monkeypatch.setattr(handler_module, "_BACKGROUND_STREAM_DRAIN_TIMEOUT_SECONDS", 0.02)
    release = asyncio.Event()

    async def producer(queue):
        await release.wait()
        await queue.enqueue_event(_status(TaskState.TASK_STATE_COMPLETED))

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    source = await handler._queue_manager.get("task")
    sink = await source.tap(evict_on_full=True)
    release.set()
    await asyncio.wait_for(stream, 2)
    assert sink.is_closed()
    assert source._dispatcher_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("resubscribe", [False, True])
async def test_disconnect_detaches_sink_without_stopping_producer(
    runtime, resubscribe, monkeypatch
):
    handler, _, _ = runtime
    release = asyncio.Event()

    async def producer(queue):
        await release.wait()
        await queue.enqueue_event(_status(TaskState.TASK_STATE_WORKING))
        await asyncio.Event().wait()

    producer_task = await handler.start_background_task_stream(task=_task(), producer=producer)
    source = await handler._queue_manager.get("task")
    tapped = asyncio.Event()
    original_tap = source.tap

    async def tap(**kwargs):
        sink = await original_tap(**kwargs)
        tapped.set()
        return sink

    monkeypatch.setattr(source, "tap", tap)
    method = handler.on_resubscribe_to_task if resubscribe else handler.on_subscribe_to_task
    subscription = method(SubscribeToTaskRequest(id="task"))
    pending = asyncio.create_task(anext(subscription))
    try:
        await asyncio.wait_for(tapped.wait(), 2)
        release.set()
        await asyncio.wait_for(pending, 2)
        source = await handler._queue_manager.get("task")
        assert len(source._sinks) == 1
        await subscription.aclose()
        assert not source._sinks
        assert not producer_task.done()
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await subscription.aclose()


@pytest.mark.asyncio
async def test_completion_between_snapshot_and_tap_replays_final_task(runtime, monkeypatch):
    handler, _, _ = runtime
    await task_store_save(handler.task_store, _task(), ServerCallContext())
    source = await handler._queue_manager.create("task")
    original_tap = source.tap

    async def complete_before_tap(**kwargs):
        final = _task()
        final.status.state = TaskState.TASK_STATE_COMPLETED
        await task_store_save(handler.task_store, final, ServerCallContext())
        await source.close(immediate=True)
        return await original_tap(**kwargs)

    monkeypatch.setattr(source, "tap", complete_before_tap)
    events = [
        event async for event in handler.on_subscribe_to_task(SubscribeToTaskRequest(id="task"))
    ]
    assert len(events) == 1
    assert events[0].status.state == TaskState.TASK_STATE_COMPLETED


@pytest.mark.asyncio
async def test_duplicate_stream_registration_preserves_existing_snapshot(runtime):
    handler, _, _ = runtime
    producer = AsyncMock()
    await handler._queue_manager.create("task")
    task = _task()
    await task_store_save(handler.task_store, task, ServerCallContext())
    replacement = _task()
    replacement.status.state = TaskState.TASK_STATE_FAILED
    with pytest.raises(ValueError, match="already exists"):
        await handler.start_background_task_stream(task=replacement, producer=producer)
    producer.assert_not_awaited()
    assert await handler.on_get_task(GetTaskRequest(id="task")) == task


@pytest.mark.asyncio
async def test_failed_persistence_is_not_broadcast_or_retried(runtime, monkeypatch):
    from codex_a2a.server.task_store import TaskStoreOperationError

    handler, store, _ = runtime
    release = asyncio.Event()

    async def producer(queue):
        await release.wait()
        await queue.enqueue_event(_status(TaskState.TASK_STATE_COMPLETED))

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    failed_save = AsyncMock(side_effect=TaskStoreOperationError("save", "task"))
    monkeypatch.setattr(store.task_store, "save", failed_save)
    source = await handler._queue_manager.get("task")
    sink = await source.tap(evict_on_full=True)
    release.set()
    with pytest.raises(TaskStoreOperationError):
        await asyncio.wait_for(stream, 2)
    failed_save.assert_awaited_once()
    with pytest.raises(QueueShutDown):
        await sink.dequeue_event()
    assert (await handler.on_get_task(GetTaskRequest(id="task"))).status.state == (
        TaskState.TASK_STATE_WORKING
    )
