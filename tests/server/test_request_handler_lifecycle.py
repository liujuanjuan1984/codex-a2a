from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import (
    GetTaskRequest,
    Message,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.server.agent_card import build_agent_card
from codex_a2a.server.request_handler import CodexRequestHandler
from tests.support.settings import make_settings


def _handler(execute=None) -> CodexRequestHandler:
    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=execute)
    return CodexRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=build_agent_card(make_settings(a2a_bearer_token="test-token")),
    )


def _task(task_id: str = "background") -> Task:
    return Task(
        id=task_id,
        context_id="context",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )


def _params(*, blocking: bool = True) -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id="original-message",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        ),
        configuration=SendMessageConfiguration(return_immediately=not blocking),
    )


@pytest.mark.asyncio
async def test_aclose_drains_sdk_tasks_and_rejects_new_work() -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def execute(context, queue):
        await queue.enqueue_event(
            Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    handler = _handler(execute)
    try:
        result = await asyncio.wait_for(handler.on_message_send(_params(blocking=False)), 2)
        await asyncio.wait_for(started.wait(), 2)
        active = await handler._active_task_registry.get(result.id)
        assert active is not None
        tasks = [active._producer_task, active._consumer_task]
        await asyncio.wait_for(handler.aclose(), 2)
        await handler.aclose()
        assert stopped.is_set()
        assert all(task.done() for task in tasks)
        assert await handler._active_task_registry.get(result.id) is None
        with pytest.raises(RuntimeError, match="closed"):
            await handler.on_message_send(_params())
    finally:
        await handler.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk_close_fails", [False, True])
async def test_aclose_drains_adapter_streams_and_undrained_queues(
    monkeypatch, sdk_close_fails
) -> None:
    handler = _handler()
    started = asyncio.Event()
    stopped = asyncio.Event()
    cleanup_state = TaskStatusUpdateEvent(
        task_id="background",
        context_id="context",
        status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
    )

    async def producer(queue):
        started.set()
        try:
            # More events than the default queue capacity, with no consumer.
            for _ in range(2048):
                await queue.enqueue_event(_task())
            # Queue shutdown must also cancel producers waiting on unrelated I/O.
            await asyncio.Event().wait()
        finally:
            await queue.enqueue_event(cleanup_state)
            stopped.set()

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    await asyncio.wait_for(started.wait(), 2)
    source = await handler._queue_manager.get("background")
    tap = await source.tap()
    if sdk_close_fails:
        monkeypatch.setattr(
            DefaultRequestHandler, "aclose", AsyncMock(side_effect=RuntimeError("sdk close"))
        )
        with pytest.raises(RuntimeError, match="sdk close"):
            await asyncio.wait_for(handler.aclose(), 2)
    else:
        await asyncio.wait_for(handler.aclose(), 2)
        await handler.aclose()
    assert stopped.is_set()
    assert stream.cancelled()
    assert source.is_closed() and tap.is_closed()
    assert await handler._queue_manager.get("background") is None
    assert not handler._background_tasks
    assert not handler._producer_tasks
    stored = await handler.on_get_task(GetTaskRequest(id="background"))
    assert stored.status.state == TaskState.TASK_STATE_CANCELED
    producer_mock = AsyncMock()
    with pytest.raises(RuntimeError, match="closed"):
        await handler.start_background_task_stream(task=_task("late"), producer=producer_mock)
    producer_mock.assert_not_awaited()
    assert await handler.task_store.get("late", ServerCallContext()) is None


@pytest.mark.asyncio
async def test_aclose_drains_stream_cancelled_before_first_execution() -> None:
    handler = _handler()
    producer = AsyncMock()
    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    stream.cancel()
    await asyncio.wait_for(handler.aclose(), 2)
    assert stream.cancelled()
    producer.assert_not_awaited()
    assert await handler._queue_manager.get("background") is None


@pytest.mark.asyncio
async def test_aclose_observes_failed_background_stream(caplog) -> None:
    handler = _handler()
    stream = await handler.start_background_task_stream(
        task=_task(), producer=AsyncMock(side_effect=RuntimeError("producer failed"))
    )
    await asyncio.wait({stream}, timeout=2)
    await handler.aclose()
    assert stream.done()
    assert "Error draining background stream" in caplog.text
    assert not handler._producer_tasks


@pytest.mark.asyncio
async def test_shutdown_waits_for_inflight_stream_registration(monkeypatch) -> None:
    handler = _handler()
    saving = asyncio.Event()
    release_save = asyncio.Event()
    save = handler.task_store.save

    async def delayed_save(task, context):
        saving.set()
        await release_save.wait()
        await save(task, context)

    monkeypatch.setattr(handler.task_store, "save", delayed_save)
    registration = asyncio.create_task(
        handler.start_background_task_stream(task=_task(), producer=AsyncMock())
    )
    await asyncio.wait_for(saving.wait(), 2)
    closing = asyncio.create_task(handler.aclose())
    release_save.set()
    stream, _ = await asyncio.wait_for(asyncio.gather(registration, closing), 2)
    assert stream.done()
    assert not handler._background_tasks
    assert await handler._queue_manager.get("background") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [None, "handler", "peers", "client", "runtime", "push", "tasks", "preflight"],
)
async def test_lifespan_closes_in_dependency_order_even_after_error(monkeypatch, failure) -> None:
    from types import SimpleNamespace

    import codex_a2a.server.application as app_module
    from tests.support.dummy_clients import DummyChatCodexClient

    calls = []

    def close(name):
        async def callback(*args):
            calls.append(name)
            if failure == name:
                raise RuntimeError(f"close failed: {name}")

        return callback

    engine = SimpleNamespace(dispose=close("engine"))
    monkeypatch.setattr(app_module, "build_database_engine", lambda settings: engine)
    monkeypatch.setattr(
        app_module,
        "build_task_store_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            task_store=InMemoryTaskStore(), startup=AsyncMock(), shutdown=close("tasks")
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_push_config_store_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            push_config_store=None, startup=AsyncMock(), shutdown=close("push")
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_runtime_state_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            state_store=None, startup=AsyncMock(), shutdown=close("runtime")
        ),
    )
    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    monkeypatch.setattr(DummyChatCodexClient, "close", close("client"))
    monkeypatch.setattr(app_module.A2AClientManager, "close_all", close("peers"))
    monkeypatch.setattr(CodexRequestHandler, "aclose", close("handler"))
    if failure == "preflight":
        monkeypatch.setattr(
            DummyChatCodexClient, "startup_preflight", AsyncMock(side_effect=RuntimeError(failure))
        )
    app = app_module.create_app(
        make_settings(a2a_bearer_token="test-token", a2a_database_url="sqlite+aiosqlite://")
    )

    async def run():
        async with app.router.lifespan_context(app):
            pass

    if failure is None:
        await run()
    else:
        with pytest.raises(RuntimeError, match=failure):
            await run()
    assert calls == ["handler", "peers", "client", "runtime", "push", "tasks", "engine"]


@pytest.mark.asyncio
async def test_lifespan_releases_started_stores_if_later_startup_fails(monkeypatch) -> None:
    from types import SimpleNamespace

    import codex_a2a.server.application as app_module
    from tests.support.dummy_clients import DummyChatCodexClient

    task_shutdown = AsyncMock()
    push_shutdown = AsyncMock()
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(app_module, "build_database_engine", lambda settings: engine)
    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    monkeypatch.setattr(
        app_module,
        "build_task_store_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            task_store=InMemoryTaskStore(), startup=AsyncMock(), shutdown=task_shutdown
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_push_config_store_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            push_config_store=None,
            startup=AsyncMock(side_effect=RuntimeError("push startup")),
            shutdown=push_shutdown,
        ),
    )
    app = app_module.create_app(
        make_settings(a2a_bearer_token="test-token", a2a_database_url="sqlite+aiosqlite://")
    )
    with pytest.raises(RuntimeError, match="push startup"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup unexpectedly succeeded")
    task_shutdown.assert_awaited_once()
    push_shutdown.assert_not_awaited()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_preserves_cleanup_of_already_cancelled_producer() -> None:
    handler = _handler()
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleaned = asyncio.Event()

    async def producer(queue):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release_cleanup.wait()
            cleaned.set()

    stream = await handler.start_background_task_stream(task=_task(), producer=producer)
    await started.wait()
    stream.cancel()
    await cleaning.wait()
    closing = asyncio.create_task(handler.aclose())
    try:
        # A shutdown must wait for the pending finalizer, not cancel it again.
        done, _ = await asyncio.wait({closing}, timeout=0.02)
        assert not done
    finally:
        release_cleanup.set()
        await asyncio.wait_for(closing, 2)
    assert cleaned.is_set()
