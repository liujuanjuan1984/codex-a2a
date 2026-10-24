from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextlib import aclosing

from a2a.server.agent_execution import (
    RequestContext,
    RequestContextBuilder,
    SimpleRequestContextBuilder,
)
from a2a.server.agent_execution.active_task import INTERRUPTED_TASK_STATES, TERMINAL_TASK_STATES
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue, QueueShutDown
from a2a.server.events.event_queue_v2 import EventQueueSource
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskManager
from a2a.types import (
    Artifact,
    CancelTaskRequest,
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
from a2a.utils.errors import (
    InternalError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from a2a.utils.task import apply_history_length
from sqlalchemy.exc import SQLAlchemyError

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.media_modes import DEFAULT_OUTPUT_MEDIA_MODES, TEXT_PLAIN_MEDIA_MODE
from codex_a2a.metrics import (
    A2A_STREAM_ACTIVE,
    A2A_STREAM_REQUESTS_TOTAL,
    get_metrics_registry,
)
from codex_a2a.server.output_negotiation import (
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
    task_store_get,
    task_store_save,
)

logger = logging.getLogger(__name__)
_CANCELED_TASK_STATES = frozenset({TaskState.TASK_STATE_CANCELED})


_BACKGROUND_STREAM_DRAIN_TIMEOUT_SECONDS = 1.0


class _BackgroundQueueManager:
    """Adapter-owned registry, independent of the SDK's legacy QueueManager."""

    def __init__(self) -> None:
        self._queues: dict[str, EventQueueSource] = {}

    async def get(self, task_id: str) -> EventQueueSource | None:
        return self._queues.get(task_id)

    async def create(self, task_id: str) -> EventQueueSource:
        if task_id in self._queues:
            raise ValueError(f"Background stream already exists: {task_id}")
        # Persistence is handled by the producer; there is no default consumer.
        queue = EventQueueSource(create_default_sink=False)
        self._queues[task_id] = queue
        return queue

    async def aclose(self) -> None:
        queues = list(self._queues.values())
        self._queues.clear()
        await asyncio.gather(*(queue.close(immediate=True) for queue in queues))


class _OutputModeAwareRequestContextBuilder(RequestContextBuilder):
    """Record negotiated output modes before the SDK materializes a task."""

    def __init__(
        self,
        inner: RequestContextBuilder,
        *,
        remember: Callable[[str, list[str] | None], None],
    ) -> None:
        self._inner = inner
        self._remember = remember

    async def build(
        self,
        context: ServerCallContext,
        params: SendMessageRequest | None = None,
        task_id: str | None = None,
        context_id: str | None = None,
        task: Task | None = None,
    ) -> RequestContext:
        request_context = await self._inner.build(
            context=context,
            params=params,
            task_id=task_id,
            context_id=context_id,
            task=task,
        )
        if params is not None and request_context.task_id:
            self._remember(
                request_context.task_id,
                CodexRequestHandler._accepted_output_modes_from_params(params),
            )
        return request_context


class CodexRequestHandler(DefaultRequestHandler):
    """Harden request lifecycle behavior around cancel, subscribe, and disconnects."""

    _metrics = get_metrics_registry()

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self._task_output_modes: dict[str, frozenset[str]] = {}
        super_args = list(args)
        if len(super_args) > 6:
            request_context_builder: RequestContextBuilder | None = super_args[6]
        else:
            request_context_builder = kwargs.pop("request_context_builder", None)
        if request_context_builder is None:
            request_context_builder = SimpleRequestContextBuilder(
                should_populate_referred_tasks=False,
                task_store=None,
            )
        wrapped_builder = _OutputModeAwareRequestContextBuilder(
            request_context_builder,
            remember=self._remember_task_output_modes,
        )
        if len(super_args) > 6:
            super_args[6] = wrapped_builder
        else:
            kwargs["request_context_builder"] = wrapped_builder
        super().__init__(*super_args, **kwargs)
        self._background_tasks: set[asyncio.Task] = set()
        self._queue_manager = _BackgroundQueueManager()
        self._producer_tasks: dict[str, asyncio.Task] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._closed = False

    async def aclose(self) -> None:
        """Drain SDK tasks and adapter streams while their dependencies are alive."""
        async with self._lifecycle_lock:
            self._closed = True
            try:
                await super().aclose()
            finally:
                try:
                    # Unblock producers, including cleanup that emits final events.
                    await self._queue_manager.aclose()
                finally:
                    tasks = set(self._background_tasks) | set(self._producer_tasks.values())
                    for task in tasks:
                        # A second cancel can interrupt persistence in a finalizer.
                        if not task.done() and not task.cancelling():
                            task.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            logger.error("Error draining background stream", exc_info=result)
                    self._background_tasks.clear()
                    self._producer_tasks.clear()
                    self._task_output_modes.clear()

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _discard(done_task: asyncio.Task) -> None:
            self._background_tasks.discard(done_task)

        task.add_done_callback(_discard)

    async def _register_producer(self, task_id: str, producer_task: asyncio.Task) -> None:
        self._producer_tasks[task_id] = producer_task

    async def on_get_task(
        self,
        params: GetTaskRequest,
        context=None,
    ):
        store_context = self._task_store_context(context)
        try:
            task = await super().on_get_task(params, store_context)
            accepted_output_modes = self._accepted_output_modes_for_task(
                task_id=params.id, task=task
            )
            return apply_accepted_output_modes(task, accepted_output_modes)
        except (TaskStoreOperationError, SQLAlchemyError) as exc:
            if isinstance(exc, SQLAlchemyError):
                exc = TaskStoreOperationError("get", params.id)
            raise self._task_store_server_error(exc) from exc

    async def start_background_task_stream(
        self,
        *,
        task: Task,
        context=None,
        producer,
    ) -> asyncio.Task:
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("CodexRequestHandler is closed")
            if await self._queue_manager.get(task.id) is not None:
                raise ValueError(f"Background stream already exists: {task.id}")
            return await self._start_background_task_stream(
                task=task, context=context, producer=producer
            )

    async def _start_background_task_stream(
        self,
        *,
        task: Task,
        context=None,
        producer,
    ) -> asyncio.Task:
        store_context = self._task_store_context(context)
        await task_store_save(self.task_store, task, store_context)
        source_queue = await self._queue_manager.create(task.id)
        task_manager = TaskManager(
            task_id=task.id,
            context_id=task.context_id,
            task_store=self.task_store,
            initial_message=None,
            context=store_context,
        )

        accepted_output_modes = self._accepted_output_modes_for_task(task_id=task.id, task=task)

        class _PersistingEventQueue(EventQueue):
            async def enqueue_event(self, event) -> None:  # noqa: ANN001
                event = annotate_output_negotiation_metadata(event, accepted_output_modes)
                # Persist once, before broadcasting. Subscribers only project events.
                await task_manager.process(event)
                await source_queue.enqueue_event(event)

            async def close(self) -> None:
                await source_queue.close(immediate=True)

        started = asyncio.Event()
        run_producer = asyncio.Event()

        async def _run_stream() -> None:
            queue = _PersistingEventQueue()
            try:
                started.set()
                await run_producer.wait()
                await producer(queue)
            except TaskStoreOperationError:
                raise
            except Exception:
                current_task = await task_store_get(self.task_store, task.id, store_context)
                if (
                    current_task is not None
                    and current_task.status.state not in TERMINAL_TASK_STATES
                ):
                    await queue.enqueue_event(
                        TaskStatusUpdateEvent(
                            task_id=task.id,
                            context_id=task.context_id,
                            status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
                        )
                    )
                raise
            finally:
                try:
                    # Let healthy subscribers receive the final events; never wait
                    # indefinitely for an abandoned sink to acknowledge its buffer.
                    if not self._closed:
                        async with asyncio.timeout(_BACKGROUND_STREAM_DRAIN_TIMEOUT_SECONDS):
                            await source_queue.close()
                except TimeoutError:
                    logger.warning("Background stream drain timed out task_id=%s", task.id)
                finally:
                    await source_queue.close(immediate=True)

        stream_task = asyncio.create_task(_run_stream())
        stream_task.set_name(f"background_stream:{task.id}")
        await self._register_producer(task.id, stream_task)
        self._track_background_task(stream_task)
        # Enter the cleanup scope before exposing a cancellable task handle.
        try:
            await started.wait()
        finally:
            run_producer.set()
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
            task = await task_store_get(self.task_store, params.id, store_context)
            if not task:
                raise TaskNotFoundError()

            # Repeated cancel of an already-canceled task is idempotent.
            if task.status.state in _CANCELED_TASK_STATES:
                return task

            if task.status.state in TERMINAL_TASK_STATES:
                state_name = TaskState.Name(task.status.state)
                raise TaskNotCancelableError(
                    message=f"Task cannot be canceled - current state: {state_name}"
                )

            try:
                return await super().on_cancel_task(params, store_context)
            except TaskNotCancelableError:
                refreshed = await task_store_get(self.task_store, params.id, store_context)
                if refreshed and refreshed.status.state in _CANCELED_TASK_STATES:
                    return refreshed
                raise
        except (TaskStoreOperationError, SQLAlchemyError) as exc:
            if isinstance(exc, SQLAlchemyError):
                exc = TaskStoreOperationError("get", params.id)
            raise self._task_store_server_error(exc) from exc

    async def on_subscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context=None,
    ):
        store_context = self._task_store_context(context)
        try:
            task = await task_store_get(self.task_store, params.id, store_context)
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
            source = await self._queue_manager.get(task.id)
            if source is None:
                async with aclosing(
                    super().on_subscribe_to_task(params, store_context)
                ) as subscription:
                    async for event in subscription:
                        negotiated_event = apply_accepted_output_modes(event, accepted_output_modes)
                        if negotiated_event is None:
                            continue
                        yield negotiated_event
                return

            try:
                queue = await source.tap(evict_on_full=True)
            except QueueShutDown:
                # The producer may have finished after the initial snapshot read.
                refreshed = await self.on_get_task(GetTaskRequest(id=task.id), store_context)
                if refreshed is not None:
                    yield refreshed
                return
            try:
                while True:
                    try:
                        event = await queue.dequeue_event()
                    except QueueShutDown:
                        return
                    queue.task_done()
                    negotiated_event = apply_accepted_output_modes(event, accepted_output_modes)
                    if negotiated_event is not None:
                        yield annotate_output_negotiation_metadata(
                            negotiated_event, accepted_output_modes
                        )
                    if self._is_terminal_subscription_event(event):
                        return
            finally:
                await queue.close(immediate=True)
        except (TaskStoreOperationError, SQLAlchemyError) as exc:
            if isinstance(exc, SQLAlchemyError):
                exc = TaskStoreOperationError("get", params.id)
            raise self._task_store_server_error(exc) from exc

    async def on_resubscribe_to_task(
        self,
        params: SubscribeToTaskRequest,
        context=None,
    ):
        async with aclosing(self.on_subscribe_to_task(params, context)) as subscription:
            async for event in subscription:
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
        except (TaskStoreOperationError, SQLAlchemyError) as exc:
            if isinstance(exc, SQLAlchemyError):
                exc = TaskStoreOperationError("save", task_id)
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
        except (TaskStoreOperationError, SQLAlchemyError) as exc:
            if isinstance(exc, SQLAlchemyError):
                exc = TaskStoreOperationError("save", task_id)
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
