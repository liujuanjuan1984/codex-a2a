from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from a2a.server.agent_execution.active_task import INTERRUPTED_TASK_STATES, TERMINAL_TASK_STATES
from a2a.server.context import ServerCallContext
from a2a.server.events import EventConsumer
from a2a.server.events.event_queue import EventQueueLegacy
from a2a.server.events.queue_manager import QueueManager
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.default_request_handler_v2 import validate_history_length
from a2a.server.tasks import TaskManager
from a2a.types import (
    Artifact,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Role,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import (
    InternalError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from a2a.utils.task import apply_history_length

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.media_modes import DEFAULT_OUTPUT_MEDIA_MODES, TEXT_PLAIN_MEDIA_MODE
from codex_a2a.metrics import (
    A2A_STREAM_ACTIVE,
    A2A_STREAM_REQUESTS_TOTAL,
    get_metrics_registry,
)
from codex_a2a.server.output_negotiation import (
    NegotiatingResultAggregator,
    annotate_output_negotiation_metadata,
    apply_accepted_output_modes,
    extract_accepted_output_modes_from_metadata,
    media_mode_is_accepted,
    normalize_accepted_output_modes,
)
from codex_a2a.server.task_store import (
    TaskStoreOperationError,
    build_task_store_failure_metadata,
    task_store_failure_message,
)

logger = logging.getLogger(__name__)
_CANCELED_TASK_STATES = frozenset({TaskState.TASK_STATE_CANCELED})


class _InMemoryQueueManager(QueueManager):
    def __init__(self) -> None:
        self._queues: dict[str, EventQueueLegacy] = {}

    async def add(self, task_id: str, queue: EventQueueLegacy) -> None:
        self._queues[task_id] = queue

    async def get(self, task_id: str) -> EventQueueLegacy | None:
        return self._queues.get(task_id)

    async def tap(self, task_id: str) -> EventQueueLegacy | None:
        queue = self._queues.get(task_id)
        if queue is None:
            return None
        return await queue.tap()

    async def close(self, task_id: str) -> None:
        queue = self._queues.pop(task_id, None)
        if queue is not None:
            await queue.close()

    async def create_or_tap(self, task_id: str) -> EventQueueLegacy:
        queue = self._queues.get(task_id)
        if queue is None:
            queue = EventQueueLegacy()
            self._queues[task_id] = queue
            return queue
        return await queue.tap()


class CodexRequestHandler(DefaultRequestHandler):
    """Harden request lifecycle behavior around cancel, subscribe, and disconnects."""

    _metrics = get_metrics_registry()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._task_output_modes: dict[str, frozenset[str]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._queue_manager: QueueManager = _InMemoryQueueManager()
        self._producer_tasks: dict[str, asyncio.Task] = {}

    async def _send_push_notification_if_needed(  # noqa: ANN001
        self,
        task_id: str,
        result_aggregator,
    ) -> None:
        del task_id, result_aggregator

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _discard(done_task: asyncio.Task) -> None:
            self._background_tasks.discard(done_task)

        task.add_done_callback(_discard)

    async def _register_producer(self, task_id: str, producer_task: asyncio.Task) -> None:
        self._producer_tasks[task_id] = producer_task

    async def _cleanup_producer(self, producer_task: asyncio.Task, task_id: str) -> None:
        current = self._producer_tasks.get(task_id)
        if current is producer_task:
            self._producer_tasks.pop(task_id, None)
        with contextlib.suppress(asyncio.CancelledError):
            await producer_task

    async def on_get_task(
        self,
        params: GetTaskRequest,
        context=None,
    ):
        store_context = self._task_store_context(context)
        try:
            # A2A SDK 1.0.2 currently validates GetTaskRequest through a protobuf
            # field API that is incompatible with protobuf 7.x. Mirror the small
            # upstream get-task flow here so the server remains usable on current deps.
            validate_history_length(params)
            task = await self.task_store.get(params.id, store_context)
            if task is None:
                raise TaskNotFoundError()
            accepted_output_modes = self._accepted_output_modes_for_task(
                task_id=params.id, task=task
            )
            task = apply_history_length(task, params)
            return apply_accepted_output_modes(task, accepted_output_modes)
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    async def _setup_active_task(self, params, context=None):  # noqa: ANN001
        active_task, request_context = await super()._setup_active_task(params, context)
        task_id = getattr(request_context, "task_id", None)
        if isinstance(task_id, str) and task_id:
            self._remember_task_output_modes(
                task_id,
                self._accepted_output_modes_from_params(params),
            )
        return active_task, request_context

    async def start_background_task_stream(
        self,
        *,
        task: Task,
        context=None,
        producer,
    ) -> asyncio.Task:
        store_context = self._task_store_context(context)
        await self.task_store.save(task, store_context)
        source_queue = await self._queue_manager.create_or_tap(task.id)
        task_manager = TaskManager(
            task_id=task.id,
            context_id=task.context_id,
            task_store=self.task_store,
            initial_message=None,
            context=store_context,
        )

        class _PersistingEventQueue:
            async def enqueue_event(self, event) -> None:  # noqa: ANN001
                await source_queue.enqueue_event(event)
                await task_manager.process(event)

            async def close(self) -> None:
                await source_queue.close(immediate=True)

        async def _run_stream() -> None:
            try:
                await producer(_PersistingEventQueue())
            finally:
                await source_queue.close(immediate=True)

        stream_task = asyncio.create_task(_run_stream())
        stream_task.set_name(f"background_stream:{task.id}")
        await self._register_producer(task.id, stream_task)
        self._track_background_task(stream_task)
        return stream_task

    @classmethod
    def _task_store_server_error(cls, exc: TaskStoreOperationError) -> InternalError:
        return InternalError(message=task_store_failure_message(exc.operation))

    @classmethod
    def _task_store_failure_task(
        cls,
        *,
        task_id: str,
        context_id: str,
        operation: str,
    ) -> Task:
        message_text = task_store_failure_message(operation)
        error_message = Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_AGENT,
            parts=[new_text_part(message_text)],
            task_id=task_id,
            context_id=context_id,
        )
        return Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_FAILED, message=error_message),
            history=[error_message],
            metadata=build_task_store_failure_metadata(operation),
        )

    @classmethod
    def _task_store_failure_events(
        cls,
        *,
        task_id: str,
        context_id: str,
        operation: str,
    ) -> tuple[TaskArtifactUpdateEvent, TaskStatusUpdateEvent]:
        message_text = task_store_failure_message(operation)
        return (
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=f"{task_id}:task-store-error",
                    parts=[new_text_part(message_text)],
                ),
                append=False,
                last_chunk=True,
            ),
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
                metadata=build_task_store_failure_metadata(operation),
            ),
        )

    @staticmethod
    def _resolve_context_id_from_params(params, task_id: str) -> str:  # noqa: ANN001
        message = getattr(params, "message", None)
        context_id = getattr(message, "contextId", None) or getattr(message, "context_id", None)
        return context_id or task_id

    @staticmethod
    def _accepted_output_modes_from_params(params) -> list[str] | None:  # noqa: ANN001
        configuration = getattr(params, "configuration", None)
        if configuration is None:
            return None
        return getattr(configuration, "accepted_output_modes", None) or getattr(
            configuration,
            "acceptedOutputModes",
            None,
        )

    @classmethod
    def _validate_chat_output_modes(cls, params) -> None:  # noqa: ANN001
        accepted_output_modes = normalize_accepted_output_modes(
            cls._accepted_output_modes_from_params(params)
        )
        if accepted_output_modes is None:
            return

        supported_output_modes = list(DEFAULT_OUTPUT_MEDIA_MODES)
        if not any(
            media_mode_is_accepted(media_mode, accepted_output_modes)
            for media_mode in supported_output_modes
        ):
            raise UnsupportedOperationError(
                message=(
                    "Requested acceptedOutputModes are not compatible with Codex chat responses."
                ),
                data={
                    "accepted_output_modes": sorted(accepted_output_modes),
                    "supported_output_modes": supported_output_modes,
                },
            )

        if not media_mode_is_accepted(TEXT_PLAIN_MEDIA_MODE, accepted_output_modes):
            raise UnsupportedOperationError(
                message="Codex chat responses require text/plain in acceptedOutputModes.",
                data={
                    "accepted_output_modes": sorted(accepted_output_modes),
                    "required_output_modes": [TEXT_PLAIN_MEDIA_MODE],
                    "supported_output_modes": supported_output_modes,
                },
            )

    def _remember_task_output_modes(
        self,
        task_id: str,
        accepted_output_modes: list[str] | None,
    ) -> None:
        normalized = normalize_accepted_output_modes(accepted_output_modes)
        if normalized is None:
            self._task_output_modes.pop(task_id, None)
            return
        self._task_output_modes[task_id] = normalized

    def _accepted_output_modes_for_task(
        self,
        *,
        task_id: str,
        task: Task | None,
    ) -> frozenset[str] | None:
        if task_id in self._task_output_modes:
            return self._task_output_modes[task_id]
        if task is None:
            return None
        return extract_accepted_output_modes_from_metadata(task.metadata)

    def _clear_task_output_modes(self, task_id: str) -> None:
        self._task_output_modes.pop(task_id, None)

    @staticmethod
    def _task_store_context(context) -> ServerCallContext:  # noqa: ANN001
        return context if isinstance(context, ServerCallContext) else ServerCallContext()

    async def on_cancel_task(
        self,
        params: CancelTaskRequest,
        context=None,
    ) -> Task | None:
        store_context = self._task_store_context(context)
        try:
            task = await self.task_store.get(params.id, store_context)
            if not task:
                raise TaskNotFoundError()

            # Repeated cancel of an already-canceled task is idempotent.
            if task.status.state in _CANCELED_TASK_STATES:
                return task

            if task.status.state in TERMINAL_TASK_STATES:
                raise TaskNotCancelableError(
                    message=f"Task cannot be canceled - current state: {task.status.state}"
                )

            try:
                return await super().on_cancel_task(params, store_context)
            except TaskNotCancelableError:
                refreshed = await self.task_store.get(params.id, store_context)
                if refreshed and refreshed.status.state in _CANCELED_TASK_STATES:
                    return refreshed
                raise
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    async def on_subscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context=None,
    ):
        store_context = self._task_store_context(context)
        try:
            task = await self.task_store.get(params.id, store_context)
            if not task:
                raise TaskNotFoundError()

            # Terminal tasks replay once and close cleanly.
            if task.status.state in TERMINAL_TASK_STATES:
                accepted_output_modes = self._accepted_output_modes_for_task(
                    task_id=params.id,
                    task=task,
                )
                negotiated_task = apply_accepted_output_modes(task, accepted_output_modes)
                if negotiated_task is not None:
                    yield negotiated_task
                return

            accepted_output_modes = self._accepted_output_modes_for_task(
                task_id=params.id,
                task=task,
            )
            queue = await self._queue_manager.tap(task.id)
            if queue is None:
                async for event in super().on_subscribe_to_task(params, store_context):
                    negotiated_event = apply_accepted_output_modes(event, accepted_output_modes)
                    if negotiated_event is None:
                        continue
                    yield negotiated_event
                return

            task_manager = TaskManager(
                task_id=task.id,
                context_id=task.context_id,
                task_store=self.task_store,
                initial_message=None,
                context=store_context,
            )
            result_aggregator = NegotiatingResultAggregator(task_manager, accepted_output_modes)
            consumer = EventConsumer(queue)
            async for event in result_aggregator.consume_and_emit(consumer):
                yield event
                if self._is_terminal_subscription_event(event):
                    return
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    async def on_resubscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context=None,
    ):
        async for event in self.on_subscribe_to_task(params, context):
            yield event

    @staticmethod
    def _is_terminal_subscription_event(event: object) -> bool:
        if isinstance(event, Task):
            return event.status.state in TERMINAL_TASK_STATES
        if isinstance(event, TaskStatusUpdateEvent):
            return event.status.state in TERMINAL_TASK_STATES
        return False

    async def on_message_send_stream(self, params, context=None):
        self._validate_chat_output_modes(params)
        self._metrics.inc_counter(A2A_STREAM_REQUESTS_TOTAL)
        self._metrics.inc_gauge(A2A_STREAM_ACTIVE)
        task_id = getattr(getattr(params, "message", None), "task_id", None) or str(uuid.uuid4())
        accepted_output_modes = self._accepted_output_modes_from_params(params)
        stream_completed = False

        try:
            active_task, request_context = await self._setup_active_task(
                params,
                self._task_store_context(context),
            )
            task_id = request_context.task_id or task_id
            logger.debug("A2A stream request started task_id=%s", task_id)
            subscription = active_task.subscribe(
                request=request_context,
                include_initial_task=False,
            )
            try:
                async for raw_event in subscription:
                    event = raw_event
                    if isinstance(event, Task):
                        self._validate_task_id_match(task_id, event.id)
                        event = apply_history_length(event, params.configuration)
                    negotiated_event = apply_accepted_output_modes(event, accepted_output_modes)
                    if negotiated_event is None:
                        continue
                    yield annotate_output_negotiation_metadata(
                        negotiated_event,
                        accepted_output_modes,
                    )
            finally:
                close_subscription = getattr(subscription, "aclose", None)
                if callable(close_subscription):
                    await close_subscription()
            stream_completed = True
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed during streaming task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            for event in self._task_store_failure_events(
                task_id=task_id,
                context_id=self._resolve_context_id_from_params(params, task_id),
                operation=exc.operation,
            ):
                yield event
        finally:
            self._metrics.dec_gauge(A2A_STREAM_ACTIVE)
            logger.debug(
                "A2A stream request closed task_id=%s completed=%s",
                task_id,
                stream_completed,
            )
            if stream_completed:
                self._clear_task_output_modes(task_id)

    async def on_message_send(self, params, context=None):
        self._validate_chat_output_modes(params)
        task_id = getattr(getattr(params, "message", None), "task_id", None) or str(uuid.uuid4())
        accepted_output_modes = self._accepted_output_modes_from_params(params)
        active_task = None
        result = None

        try:
            active_task, request_context = await self._setup_active_task(
                params,
                self._task_store_context(context),
            )
            task_id = request_context.task_id or task_id
            logger.debug("A2A message request started task_id=%s", task_id)
            return_immediately = bool(
                params.HasField("configuration") and params.configuration.return_immediately
            )
            subscription = active_task.subscribe(
                request=request_context,
                include_initial_task=False,
                replace_status_update_with_task=True,
            )
            try:
                async for raw_event in subscription:
                    event = raw_event
                    logger.debug(
                        "Processing[%s] event [%s] %s",
                        params.message.task_id,
                        type(event).__name__,
                        event,
                    )
                    if isinstance(event, TaskStatusUpdateEvent):
                        self._validate_task_id_match(task_id, event.task_id)
                        event = await active_task.get_task()
                        logger.debug("Replaced TaskStatusUpdateEvent with Task: %s", event)

                    if isinstance(event, Task) and (
                        return_immediately
                        or event.status.state in (TERMINAL_TASK_STATES | INTERRUPTED_TASK_STATES)
                    ):
                        self._validate_task_id_match(task_id, event.id)
                        result = event
                        break

                    if isinstance(event, Message):
                        result = event
            finally:
                close_subscription = getattr(subscription, "aclose", None)
                if callable(close_subscription):
                    await close_subscription()
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed during SendMessage task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            return self._task_store_failure_task(
                task_id=task_id,
                context_id=self._resolve_context_id_from_params(params, task_id),
                operation=exc.operation,
            )
        except Exception:
            logger.exception("Agent execution failed")
            raise

        if not result:
            logger.debug("Missing result for task %s", task_id)
            if active_task is None:
                raise InternalError()
            result = await active_task.get_task()

        if isinstance(result, Task):
            self._validate_task_id_match(task_id, result.id)
            if params.configuration:
                result = apply_history_length(result, params.configuration)
        negotiated_result = apply_accepted_output_modes(result, accepted_output_modes)
        if negotiated_result is not None:
            result = annotate_output_negotiation_metadata(
                negotiated_result,
                accepted_output_modes,
            )

        if isinstance(result, Task) and result.status.state in TERMINAL_TASK_STATES:
            self._clear_task_output_modes(task_id)
        elif isinstance(result, Message):
            self._clear_task_output_modes(task_id)

        logger.debug("A2A message request completed task_id=%s", task_id)
        return result
