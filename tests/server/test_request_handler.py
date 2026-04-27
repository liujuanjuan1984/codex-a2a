from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.events import EventConsumer
from a2a.server.events.event_queue import EventQueue, EventQueueLegacy
from a2a.server.events.queue_manager import QueueManager
from a2a.server.tasks import TaskManager
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import (
    Artifact,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import InternalError, UnsupportedOperationError

from codex_a2a.a2a_proto import (
    new_data_part,
    new_file_url_part,
    new_text_part,
    part_text,
)
from codex_a2a.contracts.runtime_output import build_interrupt_metadata, build_output_metadata
from codex_a2a.server.agent_card import build_agent_card
from codex_a2a.server.output_negotiation import (
    NegotiatingResultAggregator,
    merge_output_negotiation_metadata,
)
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.task_store import TASK_STORE_ERROR_TYPE, TaskStoreOperationError
from tests.support.settings import make_settings


def _make_agent_card():
    return build_agent_card(make_settings(a2a_bearer_token="test-token"))


def _make_handler(*, task_store) -> CodexRequestHandler:
    return CodexRequestHandler(
        agent_executor=MagicMock(),
        task_store=task_store,
        agent_card=_make_agent_card(),
    )


def _server_context() -> ServerCallContext:
    return ServerCallContext()


def _make_message_send_params() -> SendMessageRequest:
    return SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        )
    )


@pytest.mark.asyncio
async def test_cancel_is_idempotent_for_already_canceled_task() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
    )
    await task_store.save(task, _server_context())

    handler = _make_handler(task_store=task_store)

    result = await handler.on_cancel_task(CancelTaskRequest(id="task-1"))

    assert result == task


@pytest.mark.asyncio
async def test_resubscribe_replays_terminal_task_once() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
    )
    await task_store.save(task, _server_context())

    handler = _make_handler(task_store=task_store)

    events = [
        event async for event in handler.on_resubscribe_to_task(SubscribeToTaskRequest(id="task-1"))
    ]

    assert events == [task]


@pytest.mark.asyncio
async def test_get_task_store_failure_maps_to_stable_server_error() -> None:
    task_store = MagicMock()
    task_store.get = AsyncMock(side_effect=TaskStoreOperationError("get", "task-1"))
    handler = _make_handler(task_store=task_store)

    with pytest.raises(InternalError, match="Task store unavailable while loading task state."):
        await handler.on_get_task(GetTaskRequest(id="task-1"))


@pytest.mark.asyncio
async def test_resubscribe_task_store_failure_maps_to_stable_server_error() -> None:
    task_store = MagicMock()
    task_store.get = AsyncMock(side_effect=TaskStoreOperationError("get", "task-1"))
    handler = _make_handler(task_store=task_store)

    with pytest.raises(InternalError, match="Task store unavailable while loading task state."):
        events = [
            event
            async for event in handler.on_resubscribe_to_task(SubscribeToTaskRequest(id="task-1"))
        ]
        assert events == []


@pytest.mark.asyncio
async def test_message_send_returns_failed_task_for_task_store_error() -> None:
    class _Aggregator:
        async def consume_and_break_on_interrupt(self, _consumer, *, blocking, event_callback):
            del _consumer, blocking, event_callback
            raise TaskStoreOperationError("save", "task-1")

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=MagicMock(),
                agent_card=_make_agent_card(),
            )
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del context
            aggregator = NegotiatingResultAggregator(
                MagicMock(),
                params.configuration.accepted_output_modes if params.configuration else None,
            )
            aggregator.consume_and_break_on_interrupt = _Aggregator().consume_and_break_on_interrupt
            return (
                MagicMock(),
                "task-1",
                self.queue,
                aggregator,
                self.producer,
            )

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del producer_task, task_id

        async def _send_push_notification_if_needed(self, task_id, result_aggregator):  # noqa: ANN001
            del task_id, result_aggregator

        def _track_background_task(self, task):  # noqa: ANN001
            task.cancel()

    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
            task_id="task-1",
            context_id="ctx-1",
        )
    )
    result = await _Handler().on_message_send(params)

    assert result.status.state == TaskState.TASK_STATE_FAILED
    assert result.metadata == {
        "codex": {
            "error": {
                "type": TASK_STORE_ERROR_TYPE,
                "operation": "save",
            }
        }
    }


@pytest.mark.asyncio
async def test_background_interrupt_resolution_updates_task_snapshot_for_get_and_resubscribe() -> (
    None
):
    async def _producer(queue: EventQueue) -> None:
        await queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
                metadata=build_output_metadata(
                    interrupt=build_interrupt_metadata(
                        request_id="perm-1",
                        interrupt_type="permission",
                        phase="asked",
                        details={"permission": "read"},
                    )
                ),
            )
        )
        await queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
                metadata=build_output_metadata(
                    interrupt=build_interrupt_metadata(
                        request_id="perm-1",
                        interrupt_type="permission",
                        phase="resolved",
                        resolution="replied",
                    )
                ),
            )
        )
        await queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        )

    async def _wait_for_completed(task_store: InMemoryTaskStore) -> Task:
        for _ in range(100):
            task = await task_store.get("task-1", _server_context())
            if task is not None and task.status.state == TaskState.TASK_STATE_COMPLETED:
                return task
            await asyncio.sleep(0.01)
        pytest.fail("task snapshot did not reach completed state after interrupt resolution")

    task_store = InMemoryTaskStore()
    handler = _make_handler(task_store=task_store)
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )

    producer_task = await handler.start_background_task_stream(task=task, producer=_producer)
    await producer_task
    stored_task = await _wait_for_completed(task_store)

    assert stored_task.status.state == TaskState.TASK_STATE_COMPLETED

    fetched_task = await handler.on_get_task(GetTaskRequest(id="task-1"))
    assert fetched_task is not None
    assert fetched_task.status.state == TaskState.TASK_STATE_COMPLETED

    replayed = [
        event async for event in handler.on_resubscribe_to_task(SubscribeToTaskRequest(id="task-1"))
    ]
    assert replayed == [fetched_task]


@pytest.mark.asyncio
async def test_message_send_stream_emits_failed_events_for_task_store_error() -> None:
    class _Aggregator:
        def consume_and_emit(self, _consumer):
            del _consumer
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise TaskStoreOperationError("save", "task-1")

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=MagicMock(),
                agent_card=_make_agent_card(),
            )
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del context
            aggregator = NegotiatingResultAggregator(
                MagicMock(),
                params.configuration.accepted_output_modes if params.configuration else None,
            )
            aggregator.consume_and_emit = _Aggregator().consume_and_emit
            return (
                MagicMock(),
                "task-1",
                self.queue,
                aggregator,
                self.producer,
            )

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del producer_task, task_id

        async def _send_push_notification_if_needed(self, task_id, result_aggregator):  # noqa: ANN001
            del task_id, result_aggregator

        def _track_background_task(self, task):  # noqa: ANN001
            task.cancel()

    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
            task_id="task-1",
            context_id="ctx-1",
        )
    )
    events = [event async for event in _Handler().on_message_send_stream(params)]

    assert len(events) == 2
    assert events[-1].status.state == TaskState.TASK_STATE_FAILED
    assert events[-1].metadata == {
        "codex": {
            "error": {
                "type": TASK_STORE_ERROR_TYPE,
                "operation": "save",
            }
        }
    }


@pytest.mark.asyncio
async def test_message_send_rejects_json_only_output_modes_before_execution() -> None:
    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=InMemoryTaskStore(),
                agent_card=_make_agent_card(),
            )
            self.setup_called = False

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
            self.setup_called = True
            raise AssertionError("_setup_message_execution should not be called")

    handler = _Handler()
    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        ),
        configuration=SendMessageConfiguration(accepted_output_modes=["application/json"]),
    )

    with pytest.raises(UnsupportedOperationError) as exc_info:
        await handler.on_message_send(params)

    assert exc_info.value.message is not None
    assert "require text/plain" in exc_info.value.message
    assert exc_info.value.data == {
        "accepted_output_modes": ["application/json"],
        "required_output_modes": ["text/plain"],
        "supported_output_modes": ["text/plain", "application/json"],
    }
    assert handler.setup_called is False


@pytest.mark.asyncio
async def test_message_send_stream_rejects_incompatible_output_modes_before_execution() -> None:
    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=InMemoryTaskStore(),
                agent_card=_make_agent_card(),
            )
            self.setup_called = False

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
            self.setup_called = True
            raise AssertionError("_setup_message_execution should not be called")

    handler = _Handler()
    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
        ),
        configuration=SendMessageConfiguration(accepted_output_modes=["image/png"]),
    )

    with pytest.raises(UnsupportedOperationError) as exc_info:
        events = [event async for event in handler.on_message_send_stream(params)]
        assert events == []

    assert exc_info.value.message is not None
    assert "not compatible" in exc_info.value.message
    assert exc_info.value.data == {
        "accepted_output_modes": ["image/png"],
        "supported_output_modes": ["text/plain", "application/json"],
    }
    assert handler.setup_called is False


@pytest.mark.asyncio
async def test_message_send_accepts_case_insensitive_output_modes() -> None:
    class _Aggregator:
        async def consume_and_break_on_interrupt(self, _consumer, *, blocking, event_callback):
            del _consumer, blocking, event_callback
            return (
                Task(
                    id="task-1",
                    context_id="ctx-1",
                    status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                ),
                False,
                None,
            )

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=MagicMock(),
                agent_card=_make_agent_card(),
            )
            self.queue = AsyncMock()
            self.producer = MagicMock()
            self.setup_called = False

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
            self.setup_called = True
            return (
                MagicMock(),
                "task-1",
                self.queue,
                _Aggregator(),
                self.producer,
            )

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del producer_task, task_id

        async def _send_push_notification_if_needed(self, task_id, result_aggregator):  # noqa: ANN001
            del task_id, result_aggregator

        def _track_background_task(self, task):  # noqa: ANN001
            task.cancel()

    handler = _Handler()

    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
            task_id="task-1",
            context_id="ctx-1",
        ),
        configuration=SendMessageConfiguration(accepted_output_modes=["Text/Plain"]),
    )

    result = await handler.on_message_send(params)

    assert isinstance(result, Task)
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert handler.setup_called is True


@pytest.mark.asyncio
async def test_stream_disconnect_cancels_producer() -> None:
    class _FakeAggregator:
        async def consume_and_emit(self, _consumer):
            task = Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
            yield task
            await asyncio.sleep(10)

    class _TestHandler(CodexRequestHandler):
        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
            queue = AsyncMock()
            producer_task = asyncio.create_task(asyncio.sleep(10))
            self._producer_task = producer_task
            self._queue = queue
            return MagicMock(), "task-1", queue, _FakeAggregator(), producer_task

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del task_id
            try:
                await producer_task
            except asyncio.CancelledError:
                pass

    handler = _TestHandler(
        agent_executor=MagicMock(),
        task_store=InMemoryTaskStore(),
        agent_card=_make_agent_card(),
    )

    stream = handler.on_message_send_stream(_make_message_send_params())
    first_event = await stream.__anext__()
    assert isinstance(first_event, Task)

    await stream.aclose()
    await asyncio.sleep(0)

    assert handler._producer_task.cancelled()
    handler._queue.close.assert_awaited_once_with(immediate=True)


@pytest.mark.asyncio
async def test_message_send_filters_unaccepted_output_parts_to_text() -> None:
    data_part = new_data_part({"kind": "state", "tool": "bash", "status": "running"})
    image_part = new_file_url_part(
        "https://example.com/screenshot.png",
        media_type="image/png",
        filename="screenshot.png",
    )
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(
            state=TaskState.TASK_STATE_COMPLETED,
            message=Message(
                message_id="m-agent",
                role=Role.ROLE_AGENT,
                parts=[data_part],
            ),
        ),
        history=[
            Message(
                message_id="m-user",
                role=Role.ROLE_USER,
                parts=[image_part],
            )
        ],
        artifacts=[
            Artifact(
                artifact_id="artifact-1",
                parts=[data_part],
            )
        ],
    )

    class _Aggregator(NegotiatingResultAggregator):
        async def consume_and_break_on_interrupt(self, _consumer, *, blocking, event_callback):
            del _consumer, blocking, event_callback
            return self._transform_event(task), False, None

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=MagicMock(),
                agent_card=_make_agent_card(),
            )
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del context
            return (
                MagicMock(),
                "task-1",
                self.queue,
                _Aggregator(MagicMock(), params.configuration.accepted_output_modes),
                self.producer,
            )

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del producer_task, task_id

        async def _send_push_notification_if_needed(self, task_id, result_aggregator):  # noqa: ANN001
            del task_id, result_aggregator

        def _track_background_task(self, task):  # noqa: ANN001
            task.cancel()

    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
            task_id="task-1",
            context_id="ctx-1",
        ),
        configuration=SendMessageConfiguration(accepted_output_modes=["text/plain"]),
    )
    result = await _Handler().on_message_send(params)

    status_part = result.status.message.parts[0]
    artifact_part = result.artifacts[0].parts[0]
    history_part = result.history[0].parts[0]

    assert part_text(status_part) == '{"kind":"state","status":"running","tool":"bash"}'
    assert part_text(artifact_part) == '{"kind":"state","status":"running","tool":"bash"}'
    assert (
        part_text(history_part)
        == "[file omitted: screenshot.png | image/png | https://example.com/screenshot.png]"
    )


@pytest.mark.asyncio
async def test_message_send_stream_filters_unaccepted_output_parts_to_text() -> None:
    update = TaskArtifactUpdateEvent(
        task_id="task-1",
        context_id="ctx-1",
        artifact=Artifact(
            artifact_id="artifact-1",
            parts=[new_data_part({"kind": "state", "tool": "bash", "status": "running"})],
        ),
        append=False,
        last_chunk=True,
    )

    class _Aggregator(NegotiatingResultAggregator):
        def consume_and_emit(self, _consumer):
            del _consumer
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_done", False):
                raise StopAsyncIteration
            self._done = True
            return self._transform_event(update)

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(
                agent_executor=MagicMock(),
                task_store=MagicMock(),
                agent_card=_make_agent_card(),
            )
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del context
            return (
                MagicMock(),
                "task-1",
                self.queue,
                _Aggregator(MagicMock(), params.configuration.accepted_output_modes),
                self.producer,
            )

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del producer_task, task_id

        async def _send_push_notification_if_needed(self, task_id, result_aggregator):  # noqa: ANN001
            del task_id, result_aggregator

        def _track_background_task(self, task):  # noqa: ANN001
            task.cancel()

    params = SendMessageRequest(
        message=Message(
            message_id="m-1",
            role=Role.ROLE_USER,
            parts=[new_text_part("hello")],
            task_id="task-1",
            context_id="ctx-1",
        ),
        configuration=SendMessageConfiguration(accepted_output_modes=["text/plain"]),
    )
    events = [event async for event in _Handler().on_message_send_stream(params)]

    assert len(events) == 1
    assert (
        part_text(events[0].artifact.parts[0])
        == '{"kind":"state","status":"running","tool":"bash"}'
    )


@pytest.mark.asyncio
async def test_get_task_applies_stored_output_negotiation() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(
            state=TaskState.TASK_STATE_COMPLETED,
            message=Message(
                message_id="m-agent",
                role=Role.ROLE_AGENT,
                parts=[new_data_part({"kind": "state", "tool": "bash"})],
            ),
        ),
        artifacts=[
            Artifact(
                artifact_id="artifact-1",
                parts=[new_data_part({"kind": "state", "tool": "bash"})],
            )
        ],
        metadata=merge_output_negotiation_metadata(None, ["text/plain"]),
    )
    await task_store.save(task, _server_context())
    handler = _make_handler(task_store=task_store)

    result = await handler.on_get_task(GetTaskRequest(id="task-1"))

    assert part_text(result.status.message.parts[0]) == '{"kind":"state","tool":"bash"}'
    assert part_text(result.artifacts[0].parts[0]) == '{"kind":"state","tool":"bash"}'


@pytest.mark.asyncio
async def test_artifact_only_task_persists_output_negotiation_metadata() -> None:
    task_store = InMemoryTaskStore()
    task_manager = TaskManager(
        task_id="task-1",
        context_id="ctx-1",
        task_store=task_store,
        initial_message=None,
        context=_server_context(),
    )
    aggregator = NegotiatingResultAggregator(task_manager, ["text/plain"])
    event = TaskArtifactUpdateEvent(
        task_id="task-1",
        context_id="ctx-1",
        artifact=Artifact(
            artifact_id="artifact-1",
            parts=[new_data_part({"kind": "state", "tool": "bash"})],
        ),
        append=False,
        last_chunk=True,
    )

    class _Consumer:
        async def consume_all(self):  # noqa: ANN201
            yield event

    await aggregator.consume_all(cast(EventConsumer, _Consumer()))

    handler = _make_handler(task_store=task_store)
    result = await handler.on_get_task(GetTaskRequest(id="task-1"))

    assert part_text(result.artifacts[0].parts[0]) == '{"kind":"state","tool":"bash"}'
    assert result.metadata == merge_output_negotiation_metadata(None, ["text/plain"])


@pytest.mark.asyncio
async def test_resubscribe_applies_stored_output_negotiation_to_live_events() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        metadata=merge_output_negotiation_metadata(None, ["text/plain"]),
    )
    await task_store.save(task, _server_context())

    source_queue = EventQueueLegacy()

    class _QueueManager(QueueManager):
        async def add(self, task_id: str, queue: EventQueueLegacy) -> None:
            del task_id, queue

        async def get(self, task_id: str) -> EventQueueLegacy | None:
            del task_id
            return source_queue

        async def tap(self, task_id):  # noqa: ANN001
            assert task_id == "task-1"
            return await source_queue.tap()

        async def close(self, task_id: str) -> None:
            del task_id

        async def create_or_tap(self, task_id: str) -> EventQueueLegacy:
            assert task_id == "task-1"
            return source_queue

    handler = _make_handler(task_store=task_store)
    handler._queue_manager = cast(QueueManager, _QueueManager())

    async def _enqueue_events() -> None:
        await asyncio.sleep(0)
        await source_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id="task-1",
                context_id="ctx-1",
                artifact=Artifact(
                    artifact_id="artifact-1",
                    parts=[new_data_part({"kind": "state", "tool": "bash", "status": "running"})],
                ),
                append=False,
                last_chunk=None,
            )
        )
        await source_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        )

    producer_task = asyncio.create_task(_enqueue_events())
    events = [
        event async for event in handler.on_resubscribe_to_task(SubscribeToTaskRequest(id="task-1"))
    ]
    await producer_task

    assert len(events) == 2
    assert (
        part_text(events[0].artifact.parts[0])
        == '{"kind":"state","status":"running","tool":"bash"}'
    )
    assert events[1].status.state == TaskState.TASK_STATE_COMPLETED


@pytest.mark.asyncio
async def test_stream_disconnect_does_not_leave_unretrieved_loop_exceptions() -> None:
    class _FakeAggregator:
        async def consume_and_emit(self, _consumer):
            task = Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
            yield task
            await asyncio.sleep(10)

    class _TestHandler(CodexRequestHandler):
        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
            queue = AsyncMock()
            producer_task = asyncio.create_task(asyncio.sleep(10))
            self._producer_task = producer_task
            self._queue = queue
            return MagicMock(), "task-1", queue, _FakeAggregator(), producer_task

        async def _cleanup_producer(self, producer_task, task_id):  # noqa: ANN001
            del task_id
            try:
                await producer_task
            except asyncio.CancelledError:
                pass

    handler = _TestHandler(
        agent_executor=MagicMock(),
        task_store=InMemoryTaskStore(),
        agent_card=_make_agent_card(),
    )
    loop = asyncio.get_running_loop()
    loop_exceptions: list[dict] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_exceptions.append(context))

    try:
        stream = handler.on_message_send_stream(_make_message_send_params())
        first_event = await stream.__anext__()
        assert isinstance(first_event, Task)

        await stream.aclose()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert handler._producer_task.cancelled()
    assert loop_exceptions == []
    assert handler._background_tasks == set()
