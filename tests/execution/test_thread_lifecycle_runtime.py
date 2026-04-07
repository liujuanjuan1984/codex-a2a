import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types import TaskArtifactUpdateEvent, TaskIdParams, TaskNotFoundError
from a2a.utils.errors import ServerError

from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from tests.execution.test_discovery_exec_runtime import RecordingRequestHandler
from tests.support.context import DummyEventQueue
from tests.support.settings import make_settings


def _artifact_updates(queue: DummyEventQueue) -> list[TaskArtifactUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]


def _part_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    part = event.artifact.parts[0]
    data = getattr(part, "data", None) or getattr(getattr(part, "root", None), "data", None)
    return data if isinstance(data, dict) else {}


class ThreadLifecycleClientStub:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.connection_scope_id = "scope-test"
        self.thread_unsubscribe_calls: list[str] = []

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

    async def thread_unsubscribe(self, thread_id: str) -> None:
        self.thread_unsubscribe_calls.append(thread_id)


class BlockingThreadLifecycleClientStub:
    def __init__(self) -> None:
        self.connection_scope_id = "scope-test"
        self.thread_unsubscribe_calls: list[str] = []

    async def stream_events(  # noqa: ANN201
        self,
        stop_event=None,  # noqa: ANN001
        *,
        directory: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        del directory
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            await asyncio.sleep(0.01)
            if False:  # pragma: no cover
                yield {}

    async def thread_unsubscribe(self, thread_id: str) -> None:
        self.thread_unsubscribe_calls.append(thread_id)


class BackgroundThreadWatchRequestHandler:
    def __init__(self) -> None:
        self.saved_tasks = []
        self.saved_contexts = []
        self.producer_tasks: dict[str, asyncio.Task[None]] = {}
        self.cancel_requests: list[dict[str, Any]] = []

    async def start_background_task_stream(self, *, task, context=None, producer=None):  # noqa: ANN001
        self.saved_tasks.append(task)
        self.saved_contexts.append(context)
        producer_task = asyncio.create_task(producer(DummyEventQueue()))
        self.producer_tasks[task.id] = producer_task
        return producer_task

    async def on_cancel_task(self, params: TaskIdParams, context=None):  # noqa: ANN001
        self.cancel_requests.append({"task_id": params.id, "context": context})
        producer_task = self.producer_tasks.get(params.id)
        if producer_task is None:
            raise ServerError(error=TaskNotFoundError())
        producer_task.cancel()
        return None


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


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_releases_owner_on_task_cancel(tmp_path) -> None:
    database_path = (tmp_path / "thread-watch.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = BackgroundThreadWatchRequestHandler()
    client = BlockingThreadLifecycleClientStub()
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )
    result: dict[str, Any] | None = None

    try:
        result = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-1"},
        )
        active_before_cancel = await runtime_state.state_store.load_active_thread_watch_owners()
        owner_before_cancel = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result["task_id"]
        )
        assert owner_before_cancel is not None
        assert len(active_before_cancel) == 1

        handler.producer_tasks[result["task_id"]].cancel()
        with pytest.raises(asyncio.CancelledError):
            await handler.producer_tasks[result["task_id"]]

        active_after_cancel = await runtime_state.state_store.load_active_thread_watch_owners()
        owner_after_cancel = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result["task_id"]
        )
        subscription_after_cancel = await runtime_state.state_store.load_thread_watch_subscription(
            subscription_key=owner_before_cancel.subscription_key
        )

        assert active_after_cancel == []
        assert owner_after_cancel is not None
        assert owner_after_cancel.status == "released"
        assert owner_after_cancel.release_reason == "task_cancel"
        assert subscription_after_cancel is not None
        assert subscription_after_cancel.owner_count == 0
        assert subscription_after_cancel.status == "released"
    finally:
        await runtime_state.shutdown()


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_release_cancels_owned_watch_task(tmp_path) -> None:
    database_path = (tmp_path / "thread-watch-release.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = BackgroundThreadWatchRequestHandler()
    client = BlockingThreadLifecycleClientStub()
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )

    try:
        result = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-1"},
        )

        release_result = await runtime.release(
            task_id=result["task_id"],
            context={"identity": "user-1"},
        )
        active_after_release = await runtime_state.state_store.load_active_thread_watch_owners()
        owner_after_release = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result["task_id"]
        )

        assert release_result["ok"] is True
        assert release_result["task_id"] == result["task_id"]
        assert release_result["owner_status"] == "released"
        assert release_result["release_reason"] == "task_cancel"
        assert release_result["remaining_owner_count"] == 0
        assert release_result["subscription_released"] is True
        assert handler.cancel_requests == [
            {"task_id": result["task_id"], "context": {"identity": "user-1"}}
        ]
        assert active_after_release == []
        assert owner_after_release is not None
        assert owner_after_release.status == "released"
        assert owner_after_release.release_reason == "task_cancel"
        assert client.thread_unsubscribe_calls == ["thr-1"]
    finally:
        await runtime_state.shutdown()


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_release_rejects_non_owner(tmp_path) -> None:
    database_path = (tmp_path / "thread-watch-release-forbidden.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = BackgroundThreadWatchRequestHandler()
    client = BlockingThreadLifecycleClientStub()
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )

    try:
        result = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-1"},
        )

        with pytest.raises(PermissionError):
            await runtime.release(
                task_id=result["task_id"],
                context={"identity": "user-2"},
            )
    finally:
        if result is not None:
            handler.producer_tasks[result["task_id"]].cancel()
            with pytest.raises(asyncio.CancelledError):
                await handler.producer_tasks[result["task_id"]]
        await runtime_state.shutdown()


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_release_skips_upstream_unsubscribe_for_broad_watch(
    tmp_path,
) -> None:
    database_path = (tmp_path / "thread-watch-release-broad.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = BackgroundThreadWatchRequestHandler()
    client = BlockingThreadLifecycleClientStub()
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )

    try:
        result = await runtime.start(
            request={"events": ["thread.started"]},
            context={"identity": "user-1"},
        )

        await runtime.release(
            task_id=result["task_id"],
            context={"identity": "user-1"},
        )

        assert client.thread_unsubscribe_calls == []
    finally:
        await runtime_state.shutdown()


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_release_skips_upstream_unsubscribe_on_scope_mismatch(
    tmp_path,
) -> None:
    database_path = (tmp_path / "thread-watch-release-scope.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = BackgroundThreadWatchRequestHandler()
    client = BlockingThreadLifecycleClientStub()
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )

    try:
        result = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-1"},
        )
        client.connection_scope_id = "scope-other"

        await runtime.release(
            task_id=result["task_id"],
            context={"identity": "user-1"},
        )

        assert client.thread_unsubscribe_calls == []
    finally:
        await runtime_state.shutdown()


@pytest.mark.asyncio
async def test_thread_lifecycle_runtime_reuses_subscription_and_reconciles_orphans(
    tmp_path,
) -> None:
    database_path = (tmp_path / "thread-watch-reconcile.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None

    handler = RecordingRequestHandler()
    client = ThreadLifecycleClientStub([])
    client.connection_scope_id = "scope-test"
    runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state.state_store,
    )

    try:
        result_1 = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-1"},
        )
        result_2 = await runtime.start(
            request={"events": ["thread.started"], "threadIds": ["thr-1"]},
            context={"identity": "user-2"},
        )

        owner_1 = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result_1["task_id"]
        )
        owner_2 = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result_2["task_id"]
        )
        assert owner_1 is not None
        assert owner_2 is not None
        assert owner_1.subscription_key == owner_2.subscription_key

        shared_subscription = await runtime_state.state_store.load_thread_watch_subscription(
            subscription_key=owner_1.subscription_key
        )
        assert shared_subscription is not None
        assert shared_subscription.owner_count == 2
        assert shared_subscription.status == "active"

        await runtime.reconcile_persisted_watches()

        active_after_reconcile = await runtime_state.state_store.load_active_thread_watch_owners()
        owner_1_after_reconcile = await runtime_state.state_store.load_thread_watch_owner(
            watch_id=result_1["task_id"]
        )
        shared_subscription_after_reconcile = (
            await runtime_state.state_store.load_thread_watch_subscription(
                subscription_key=owner_1.subscription_key
            )
        )

        assert active_after_reconcile == []
        assert owner_1_after_reconcile is not None
        assert owner_1_after_reconcile.status == "orphaned"
        assert owner_1_after_reconcile.release_reason == "restart_reconcile"
        assert shared_subscription_after_reconcile is not None
        assert shared_subscription_after_reconcile.owner_count == 0
        assert shared_subscription_after_reconcile.status == "released"
    finally:
        await runtime_state.shutdown()
