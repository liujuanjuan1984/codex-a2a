from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import (
    Artifact,
    DataPart,
    FilePart,
    FileWithUri,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskState,
    TaskStatus,
    TextPart,
)
from a2a.utils.errors import ServerError

from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.task_store import TASK_STORE_ERROR_TYPE, TaskStoreOperationError


def _make_message_send_params() -> MessageSendParams:
    return MessageSendParams(
        message=Message(
            message_id="m-1",
            role=Role.user,
            parts=[Part(root=TextPart(text="hello"))],
        )
    )


@pytest.mark.asyncio
async def test_cancel_is_idempotent_for_already_canceled_task() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.canceled),
    )
    await task_store.save(task)

    handler = CodexRequestHandler(agent_executor=MagicMock(), task_store=task_store)

    result = await handler.on_cancel_task(TaskIdParams(id="task-1"))

    assert result == task


@pytest.mark.asyncio
async def test_resubscribe_replays_terminal_task_once() -> None:
    task_store = InMemoryTaskStore()
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.completed),
    )
    await task_store.save(task)

    handler = CodexRequestHandler(agent_executor=MagicMock(), task_store=task_store)

    events = [event async for event in handler.on_resubscribe_to_task(TaskIdParams(id="task-1"))]

    assert events == [task]


@pytest.mark.asyncio
async def test_get_task_store_failure_maps_to_stable_server_error() -> None:
    task_store = MagicMock()
    task_store.get = AsyncMock(side_effect=TaskStoreOperationError("get", "task-1"))
    handler = CodexRequestHandler(agent_executor=MagicMock(), task_store=task_store)

    with pytest.raises(ServerError, match="Task store unavailable while loading task state."):
        await handler.on_get_task(TaskIdParams(id="task-1"))


@pytest.mark.asyncio
async def test_resubscribe_task_store_failure_maps_to_stable_server_error() -> None:
    task_store = MagicMock()
    task_store.get = AsyncMock(side_effect=TaskStoreOperationError("get", "task-1"))
    handler = CodexRequestHandler(agent_executor=MagicMock(), task_store=task_store)

    with pytest.raises(ServerError, match="Task store unavailable while loading task state."):
        events = [
            event async for event in handler.on_resubscribe_to_task(TaskIdParams(id="task-1"))
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
            super().__init__(agent_executor=MagicMock(), task_store=MagicMock())
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
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

    params = MessageSendParams(
        message=Message(
            message_id="m-1",
            role=Role.user,
            parts=[Part(root=TextPart(text="hello"))],
            task_id="task-1",
            context_id="ctx-1",
        )
    )
    result = await _Handler().on_message_send(params)

    assert result.status.state == TaskState.failed
    assert result.metadata == {
        "codex": {
            "error": {
                "type": TASK_STORE_ERROR_TYPE,
                "operation": "save",
            }
        }
    }


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
            super().__init__(agent_executor=MagicMock(), task_store=MagicMock())
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
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

    params = MessageSendParams(
        message=Message(
            message_id="m-1",
            role=Role.user,
            parts=[Part(root=TextPart(text="hello"))],
            task_id="task-1",
            context_id="ctx-1",
        )
    )
    events = [event async for event in _Handler().on_message_send_stream(params)]

    assert len(events) == 2
    assert events[-1].status.state == TaskState.failed
    assert events[-1].metadata == {
        "codex": {
            "error": {
                "type": TASK_STORE_ERROR_TYPE,
                "operation": "save",
            }
        }
    }


@pytest.mark.asyncio
async def test_stream_disconnect_cancels_producer() -> None:
    class _FakeAggregator:
        async def consume_and_emit(self, _consumer):
            task = Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.working),
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

    handler = _TestHandler(agent_executor=MagicMock(), task_store=InMemoryTaskStore())

    stream = handler.on_message_send_stream(_make_message_send_params())
    first_event = await stream.__anext__()
    assert isinstance(first_event, Task)

    await stream.aclose()
    await asyncio.sleep(0)

    assert handler._producer_task.cancelled()
    handler._queue.close.assert_awaited_once_with(immediate=True)


@pytest.mark.asyncio
async def test_message_send_filters_unaccepted_output_parts_to_text() -> None:
    data_part = Part(root=DataPart(data={"kind": "state", "tool": "bash", "status": "running"}))
    image_part = Part(
        root=FilePart(
            file=FileWithUri(
                uri="https://example.com/screenshot.png",
                mime_type="image/png",
                name="screenshot.png",
            )
        )
    )
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(
            state=TaskState.completed,
            message=Message(
                message_id="m-agent",
                role=Role.agent,
                parts=[data_part],
            ),
        ),
        history=[
            Message(
                message_id="m-user",
                role=Role.user,
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

    class _Aggregator:
        async def consume_and_break_on_interrupt(self, _consumer, *, blocking, event_callback):
            del _consumer, blocking, event_callback
            return task, False, None

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(agent_executor=MagicMock(), task_store=MagicMock())
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
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

    params = MessageSendParams(
        message=Message(
            message_id="m-1",
            role=Role.user,
            parts=[Part(root=TextPart(text="hello"))],
            task_id="task-1",
            context_id="ctx-1",
        ),
        configuration=MessageSendConfiguration(accepted_output_modes=["text/plain"]),
    )
    result = await _Handler().on_message_send(params)

    status_part = result.status.message.parts[0].root
    artifact_part = result.artifacts[0].parts[0].root
    history_part = result.history[0].parts[0].root

    assert isinstance(status_part, TextPart)
    assert status_part.text == '{"kind":"state","status":"running","tool":"bash"}'
    assert isinstance(artifact_part, TextPart)
    assert artifact_part.text == '{"kind":"state","status":"running","tool":"bash"}'
    assert isinstance(history_part, TextPart)
    assert (
        history_part.text
        == "[file omitted: screenshot.png | image/png | https://example.com/screenshot.png]"
    )


@pytest.mark.asyncio
async def test_message_send_stream_filters_unaccepted_output_parts_to_text() -> None:
    update = TaskArtifactUpdateEvent(
        task_id="task-1",
        context_id="ctx-1",
        artifact=Artifact(
            artifact_id="artifact-1",
            parts=[
                Part(root=DataPart(data={"kind": "state", "tool": "bash", "status": "running"}))
            ],
        ),
        append=False,
        last_chunk=True,
    )

    class _Aggregator:
        def consume_and_emit(self, _consumer):
            del _consumer
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_done", False):
                raise StopAsyncIteration
            self._done = True
            return update

    class _Handler(CodexRequestHandler):
        def __init__(self) -> None:
            super().__init__(agent_executor=MagicMock(), task_store=MagicMock())
            self.queue = AsyncMock()
            self.producer = MagicMock()

        async def _setup_message_execution(self, params, context=None):  # noqa: ANN001
            del params, context
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

    params = MessageSendParams(
        message=Message(
            message_id="m-1",
            role=Role.user,
            parts=[Part(root=TextPart(text="hello"))],
            task_id="task-1",
            context_id="ctx-1",
        ),
        configuration=MessageSendConfiguration(accepted_output_modes=["text/plain"]),
    )
    events = [event async for event in _Handler().on_message_send_stream(params)]

    assert len(events) == 1
    part = events[0].artifact.parts[0].root
    assert isinstance(part, TextPart)
    assert part.text == '{"kind":"state","status":"running","tool":"bash"}'


@pytest.mark.asyncio
async def test_stream_disconnect_does_not_leave_unretrieved_loop_exceptions() -> None:
    class _FakeAggregator:
        async def consume_and_emit(self, _consumer):
            task = Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.working),
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

    handler = _TestHandler(agent_executor=MagicMock(), task_store=InMemoryTaskStore())
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
