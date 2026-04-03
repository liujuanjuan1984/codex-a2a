from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard

from a2a.types import (
    DataPart,
    Task,
    TaskIdParams,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskState,
    TaskStatus,
)
from a2a.utils.errors import ServerError

from codex_a2a.contracts.extensions import THREAD_LIFECYCLE_SUPPORTED_EVENTS
from codex_a2a.execution.output_mapping import build_assistant_message, enqueue_artifact_update

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

    from codex_a2a.server.request_handler import CodexRequestHandler
    from codex_a2a.server.runtime_state import ThreadWatchStateRepository
    from codex_a2a.upstream.client import CodexClient


def _is_thread_watch_state_store(
    value: ThreadWatchStateRepository | None,
) -> TypeGuard[ThreadWatchStateRepository]:
    return value is not None and all(
        hasattr(value, method_name)
        for method_name in (
            "acquire_thread_watch",
            "release_thread_watch",
            "load_active_thread_watch_owners",
            "load_thread_watch_owner",
            "load_thread_watch_subscription",
        )
    )


@dataclass(slots=True)
class ThreadLifecycleWatchHandle:
    task_id: str
    context_id: str
    events: frozenset[str]
    thread_ids: frozenset[str] | None
    stop_event: asyncio.Event
    owner_identity: str
    subscription_key: str
    producer_task: asyncio.Task[Any] | None = None


class CodexThreadLifecycleRuntime:
    def __init__(
        self,
        *,
        client: CodexClient,
        request_handler: CodexRequestHandler,
        state_store: ThreadWatchStateRepository | None = None,
    ) -> None:
        self._client = client
        self._request_handler = request_handler
        self._state_store = state_store
        self._active_handles: dict[str, ThreadLifecycleWatchHandle] = {}

    async def start(
        self,
        *,
        request: dict[str, Any] | None,
        context: ServerCallContext | None,
    ) -> dict[str, Any]:
        events = self._normalize_events(request)
        thread_ids = self._normalize_thread_ids(request)
        task_id = str(uuid.uuid4())
        context_id = task_id
        owner_identity = self._resolve_identity(context)
        subscription_key = self._build_subscription_key(events=events, thread_ids=thread_ids)
        handle = ThreadLifecycleWatchHandle(
            task_id=task_id,
            context_id=context_id,
            events=events,
            thread_ids=thread_ids,
            stop_event=asyncio.Event(),
            owner_identity=owner_identity,
            subscription_key=subscription_key,
        )
        state_store = self._state_store
        if _is_thread_watch_state_store(state_store):
            await state_store.acquire_thread_watch(
                watch_id=task_id,
                owner_identity=owner_identity,
                task_id=task_id,
                context_id=context_id,
                subscription_key=subscription_key,
                connection_scope=self._client.connection_scope_id,
                event_filter=tuple(sorted(events)),
                thread_filter=tuple(sorted(thread_ids)) if thread_ids is not None else None,
            )
        metadata = {
            "codex": {
                "thread_lifecycle_watch": {
                    "events": sorted(events),
                    "thread_ids": sorted(thread_ids) if thread_ids is not None else None,
                }
            }
        }
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(
                state=TaskState.working,
                message=build_assistant_message(
                    task_id,
                    context_id,
                    (
                        "Started Codex thread lifecycle watch. Subscribe with "
                        "tasks/resubscribe to receive lifecycle signals."
                    ),
                    message_id=f"{task_id}:status:started",
                ),
            ),
            metadata=metadata,
        )
        producer_task = await self._request_handler.start_background_task_stream(
            task=task,
            context=context,
            producer=lambda event_queue: self._run_watch(handle=handle, event_queue=event_queue),
        )
        handle.producer_task = producer_task
        self._active_handles[task_id] = handle
        return {"ok": True, "task_id": task_id, "context_id": context_id}

    async def release(
        self,
        *,
        task_id: str,
        context: ServerCallContext | None,
    ) -> dict[str, Any]:
        state_store = self._state_store
        if not _is_thread_watch_state_store(state_store):
            raise RuntimeError("Thread watch release requires persisted runtime state")

        owner = await state_store.load_thread_watch_owner(watch_id=task_id)
        if owner is None:
            raise LookupError(task_id)

        owner_identity = self._resolve_identity(context)
        if owner.owner_identity != owner_identity:
            raise PermissionError(task_id)

        if owner.status == "active":
            await self._cancel_watch_task(task_id=task_id, context=context)

        release_result = await state_store.release_thread_watch(
            watch_id=task_id,
            release_reason="explicit_release",
        )
        await self._maybe_unsubscribe_upstream(release_result=release_result)
        return {
            "ok": True,
            "task_id": task_id,
            "owner_status": release_result.owner_status,
            "release_reason": release_result.release_reason,
            "subscription_key": release_result.subscription_key,
            "remaining_owner_count": release_result.remaining_owner_count,
            "subscription_released": release_result.subscription_released,
        }

    async def reconcile_persisted_watches(self) -> None:
        state_store = self._state_store
        if not _is_thread_watch_state_store(state_store):
            return
        active_owners = await state_store.load_active_thread_watch_owners()
        for owner in active_owners:
            await state_store.release_thread_watch(
                watch_id=owner.watch_id,
                release_reason="restart_reconcile",
            )

    def _normalize_events(self, request: dict[str, Any] | None) -> frozenset[str]:
        if not isinstance(request, dict):
            return frozenset(THREAD_LIFECYCLE_SUPPORTED_EVENTS)
        raw_events = request.get("events")
        if raw_events is None:
            return frozenset(THREAD_LIFECYCLE_SUPPORTED_EVENTS)
        if not isinstance(raw_events, list) or not raw_events:
            raise ValueError("request.events must be a non-empty array")
        normalized: set[str] = set()
        for item in raw_events:
            if not isinstance(item, str) or item not in THREAD_LIFECYCLE_SUPPORTED_EVENTS:
                allowed = ", ".join(THREAD_LIFECYCLE_SUPPORTED_EVENTS)
                raise ValueError(f"request.events entries must be one of: {allowed}")
            normalized.add(item)
        return frozenset(normalized)

    def _normalize_thread_ids(self, request: dict[str, Any] | None) -> frozenset[str] | None:
        if not isinstance(request, dict):
            return None
        raw_thread_ids = request.get("threadIds")
        if not isinstance(raw_thread_ids, list):
            return None
        normalized = frozenset(
            str(item).strip() for item in raw_thread_ids if isinstance(item, str) and item.strip()
        )
        return normalized or None

    async def _run_watch(self, *, handle: ThreadLifecycleWatchHandle, event_queue) -> None:  # noqa: ANN001
        release_reason = "terminal_close"
        append = False
        metadata = {
            "codex": {
                "thread_lifecycle_watch": {
                    "events": sorted(handle.events),
                    "thread_ids": sorted(handle.thread_ids) if handle.thread_ids else None,
                }
            }
        }
        try:
            async for event in self._client.stream_events(stop_event=handle.stop_event):
                payload = self._payload_from_event(event, handle=handle)
                if payload is None:
                    continue
                await enqueue_artifact_update(
                    event_queue=event_queue,
                    task_id=handle.task_id,
                    context_id=handle.context_id,
                    artifact_id=f"{handle.task_id}:thread-lifecycle",
                    part=DataPart(data=payload),
                    append=append,
                    last_chunk=None,
                    artifact_metadata=metadata,
                    event_metadata=metadata,
                )
                append = True
        except asyncio.CancelledError:
            release_reason = "task_cancel"
            raise
        finally:
            self._active_handles.pop(handle.task_id, None)
            handle.stop_event.set()
            await self._release_watch(handle=handle, release_reason=release_reason)

    def _payload_from_event(
        self,
        event: dict[str, Any],
        *,
        handle: ThreadLifecycleWatchHandle,
    ) -> dict[str, Any] | None:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return None
        properties = event.get("properties")
        if not isinstance(properties, dict):
            return None
        thread_id = properties.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        if handle.thread_ids is not None and thread_id not in handle.thread_ids:
            return None

        normalized_event = event_type.removeprefix("thread.lifecycle.")
        declared_event = f"thread.{normalized_event.replace('_', '.')}"
        if declared_event not in handle.events:
            return None

        payload: dict[str, Any] = {
            "event": declared_event,
            "thread_id": thread_id,
            "source": properties.get("source"),
        }
        kind_map = {
            "thread.started": "thread_started",
            "thread.status.changed": "thread_status_changed",
            "thread.archived": "thread_archived",
            "thread.unarchived": "thread_unarchived",
            "thread.closed": "thread_closed",
        }
        payload["kind"] = kind_map[declared_event]
        if "status" in properties:
            payload["status"] = properties.get("status")
        if "thread" in properties:
            payload["thread"] = properties.get("thread")
        codex_private = properties.get("codex")
        if isinstance(codex_private, dict):
            payload["codex"] = codex_private
        return payload

    async def _release_watch(
        self,
        *,
        handle: ThreadLifecycleWatchHandle,
        release_reason: str,
    ) -> None:
        state_store = self._state_store
        if not _is_thread_watch_state_store(state_store):
            return
        await state_store.release_thread_watch(
            watch_id=handle.task_id,
            release_reason=release_reason,
        )

    async def _cancel_watch_task(
        self,
        *,
        task_id: str,
        context: ServerCallContext | None,
    ) -> None:
        handle = self._active_handles.get(task_id)
        if handle is not None:
            handle.stop_event.set()
        try:
            await self._request_handler.on_cancel_task(TaskIdParams(id=task_id), context=context)
        except ServerError as exc:
            if not isinstance(exc.error, (TaskNotFoundError, TaskNotCancelableError)):
                raise
        if (
            handle is not None
            and handle.producer_task is not None
            and not handle.producer_task.done()
        ):
            handle.producer_task.cancel()
            try:
                await handle.producer_task
            except asyncio.CancelledError:
                pass

    async def _maybe_unsubscribe_upstream(self, *, release_result) -> None:  # noqa: ANN001
        subscription_key = release_result.subscription_key
        if not release_result.subscription_released or not isinstance(subscription_key, str):
            return
        state_store = self._state_store
        if not _is_thread_watch_state_store(state_store):
            return
        subscription = await state_store.load_thread_watch_subscription(
            subscription_key=subscription_key
        )
        if subscription is None:
            return
        if subscription.connection_scope != self._client.connection_scope_id:
            logger.info(
                "Skipping upstream thread/unsubscribe for subscription %s because "
                "connection_scope changed from %s to %s",
                subscription_key,
                subscription.connection_scope,
                self._client.connection_scope_id,
            )
            return
        if not subscription.thread_filter:
            logger.info(
                "Skipping upstream thread/unsubscribe for subscription %s because "
                "thread_filter is not concrete",
                subscription_key,
            )
            return
        for thread_id in subscription.thread_filter:
            try:
                await self._client.thread_unsubscribe(thread_id)
            except Exception:
                logger.warning(
                    "Failed upstream thread/unsubscribe for subscription %s thread_id=%s",
                    subscription_key,
                    thread_id,
                    exc_info=True,
                )

    @staticmethod
    def _build_subscription_key(
        *,
        events: frozenset[str],
        thread_ids: frozenset[str] | None,
    ) -> str:
        payload = {
            "events": sorted(events),
            "thread_ids": sorted(thread_ids) if thread_ids is not None else None,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _resolve_identity(context: ServerCallContext | None) -> str:
        state = getattr(context, "state", None)
        if isinstance(state, dict):
            identity = state.get("identity")
            if isinstance(identity, str) and identity:
                return identity
        if isinstance(context, dict):
            identity = context.get("identity")
            if isinstance(identity, str) and identity:
                return identity
        return "anonymous"
