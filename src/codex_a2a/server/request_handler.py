from __future__ import annotations

import asyncio
import logging
import uuid

from a2a.server.events import EventConsumer
from a2a.server.request_handlers.default_request_handler import (
    TERMINAL_TASK_STATES,
    DefaultRequestHandler,
)
from a2a.types import (
    Artifact,
    InternalError,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils.errors import ServerError

from codex_a2a.metrics import (
    A2A_STREAM_ACTIVE,
    A2A_STREAM_REQUESTS_TOTAL,
    get_metrics_registry,
)
from codex_a2a.server.task_store import (
    TaskStoreOperationError,
    build_task_store_failure_metadata,
    task_store_failure_message,
)

logger = logging.getLogger(__name__)


class CodexRequestHandler(DefaultRequestHandler):
    """Harden request lifecycle behavior around cancel, subscribe, and disconnects."""

    _metrics = get_metrics_registry()

    async def on_get_task(
        self,
        params,
        context=None,
    ):
        try:
            return await super().on_get_task(params, context)
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    @classmethod
    def _task_store_server_error(cls, exc: TaskStoreOperationError) -> ServerError:
        return ServerError(error=InternalError(message=task_store_failure_message(exc.operation)))

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
            role=Role.agent,
            parts=[Part(root=TextPart(text=message_text))],
            task_id=task_id,
            context_id=context_id,
        )
        return Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.failed, message=error_message),
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
                    parts=[Part(root=TextPart(text=message_text))],
                ),
                append=False,
                last_chunk=True,
            ),
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.failed),
                metadata=build_task_store_failure_metadata(operation),
                final=True,
            ),
        )

    @staticmethod
    def _resolve_context_id_from_params(params, task_id: str) -> str:  # noqa: ANN001
        message = getattr(params, "message", None)
        context_id = getattr(message, "contextId", None) or getattr(message, "context_id", None)
        return context_id or task_id

    async def on_cancel_task(
        self,
        params: TaskIdParams,
        context=None,
    ) -> Task | None:
        try:
            task = await self.task_store.get(params.id, context)
            if not task:
                raise ServerError(error=TaskNotFoundError())

            # Repeated cancel of an already-canceled task is idempotent.
            if task.status.state.value == "canceled":
                return task

            if task.status.state in TERMINAL_TASK_STATES:
                raise ServerError(
                    error=TaskNotCancelableError(
                        message=f"Task cannot be canceled - current state: {task.status.state}"
                    )
                )

            try:
                return await super().on_cancel_task(params, context)
            except ServerError as exc:
                if isinstance(exc.error, TaskNotCancelableError):
                    refreshed = await self.task_store.get(params.id, context)
                    if refreshed and refreshed.status.state.value == "canceled":
                        return refreshed
                raise
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    async def on_resubscribe_to_task(
        self,
        params: TaskIdParams,
        context=None,
    ):
        try:
            task = await self.task_store.get(params.id, context)
            if not task:
                raise ServerError(error=TaskNotFoundError())

            # Terminal tasks replay once and close cleanly.
            if task.status.state in TERMINAL_TASK_STATES:
                yield task
                return

            async for event in super().on_resubscribe_to_task(params, context):
                yield event
        except TaskStoreOperationError as exc:
            raise self._task_store_server_error(exc) from exc

    async def on_message_send_stream(self, params, context=None):
        self._metrics.inc_counter(A2A_STREAM_REQUESTS_TOTAL)
        self._metrics.inc_gauge(A2A_STREAM_ACTIVE)
        task_id = getattr(getattr(params, "message", None), "task_id", None) or str(uuid.uuid4())
        context_id = self._resolve_context_id_from_params(params, task_id)
        queue = None
        producer_task = None
        consumer = None
        stream_completed = False

        try:
            (
                _task_manager,
                task_id,
                queue,
                result_aggregator,
                producer_task,
            ) = await self._setup_message_execution(params, context)
            context_id = self._resolve_context_id_from_params(params, task_id)
            logger.debug("A2A stream request started task_id=%s", task_id)
            consumer = EventConsumer(queue)
            producer_task.add_done_callback(consumer.agent_task_callback)
            async for event in result_aggregator.consume_and_emit(consumer):
                if isinstance(event, Task):
                    self._validate_task_id_match(task_id, event.id)
                await self._send_push_notification_if_needed(task_id, result_aggregator)
                yield event
            stream_completed = True
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed during streaming task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            for event in self._task_store_failure_events(
                task_id=task_id,
                context_id=context_id,
                operation=exc.operation,
            ):
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            logger.warning("Client disconnected. Cancelling producer task %s", task_id)
            if producer_task is not None:
                producer_task.cancel()
            if queue is not None:
                await queue.close(immediate=True)
            raise
        finally:
            self._metrics.dec_gauge(A2A_STREAM_ACTIVE)
            logger.debug(
                "A2A stream request closed task_id=%s completed=%s",
                task_id,
                stream_completed,
            )
            if producer_task is not None:
                cleanup_task = asyncio.create_task(self._cleanup_producer(producer_task, task_id))
                cleanup_task.set_name(f"cleanup_producer:{task_id}")
                self._track_background_task(cleanup_task)

    async def on_message_send(self, params, context=None):
        task_id = getattr(getattr(params, "message", None), "task_id", None) or str(uuid.uuid4())
        context_id = self._resolve_context_id_from_params(params, task_id)
        queue = None
        producer_task = None
        result_aggregator = None
        result = None
        blocking = True
        interrupted_or_non_blocking = False
        continuation_task = None
        try:
            (
                _task_manager,
                task_id,
                queue,
                result_aggregator,
                producer_task,
            ) = await self._setup_message_execution(params, context)
            context_id = self._resolve_context_id_from_params(params, task_id)
            logger.debug("A2A message request started task_id=%s", task_id)
            consumer = EventConsumer(queue)
            producer_task.add_done_callback(consumer.agent_task_callback)

            if params.configuration and params.configuration.blocking is False:
                blocking = False

            async def push_notification_callback() -> None:
                await self._send_push_notification_if_needed(task_id, result_aggregator)

            (
                result,
                interrupted_or_non_blocking,
                continuation_task,
            ) = await result_aggregator.consume_and_break_on_interrupt(
                consumer,
                blocking=blocking,
                event_callback=push_notification_callback,
            )
            if continuation_task is not None:
                continuation_task.set_name(f"continue_consuming:{task_id}")
                self._track_background_task(continuation_task)
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed during message/send task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            return self._task_store_failure_task(
                task_id=task_id,
                context_id=context_id,
                operation=exc.operation,
            )
        except Exception:
            logger.exception("Agent execution failed")
            raise
        finally:
            if producer_task is None:
                pass
            elif interrupted_or_non_blocking:
                cleanup_task = asyncio.create_task(self._cleanup_producer(producer_task, task_id))
                cleanup_task.set_name(f"cleanup_producer:{task_id}")
                self._track_background_task(cleanup_task)
            else:
                try:
                    if asyncio.current_task() and asyncio.current_task().cancelled():
                        logger.warning(
                            "Client disconnected from message request. Cancelling task %s", task_id
                        )
                        producer_task.cancel()
                        if queue is not None:
                            await queue.close(immediate=True)

                    await asyncio.shield(self._cleanup_producer(producer_task, task_id))
                except asyncio.CancelledError:
                    pass

        if not result:
            raise ServerError(error=InternalError())

        if isinstance(result, Task):
            self._validate_task_id_match(task_id, result.id)
            if params.configuration:
                from a2a.utils.task import apply_history_length

                result = apply_history_length(result, params.configuration.history_length)

        try:
            if result_aggregator is not None:
                await self._send_push_notification_if_needed(task_id, result_aggregator)
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed after message/send completion task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            return self._task_store_failure_task(
                task_id=task_id,
                context_id=context_id,
                operation=exc.operation,
            )
        logger.debug("A2A message request completed task_id=%s blocking=%s", task_id, blocking)

        return result
