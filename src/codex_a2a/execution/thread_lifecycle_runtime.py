from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.types import DataPart, Task, TaskState, TaskStatus

from codex_a2a.contracts.extensions import THREAD_LIFECYCLE_SUPPORTED_EVENTS
from codex_a2a.execution.output_mapping import build_assistant_message, enqueue_artifact_update

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

    from codex_a2a.server.request_handler import CodexRequestHandler
    from codex_a2a.upstream.client import CodexClient


@dataclass(slots=True)
class ThreadLifecycleWatchHandle:
    task_id: str
    context_id: str
    events: frozenset[str]
    thread_ids: frozenset[str] | None
    stop_event: asyncio.Event


class CodexThreadLifecycleRuntime:
    def __init__(
        self,
        *,
        client: CodexClient,
        request_handler: CodexRequestHandler,
    ) -> None:
        self._client = client
        self._request_handler = request_handler

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
        handle = ThreadLifecycleWatchHandle(
            task_id=task_id,
            context_id=context_id,
            events=events,
            thread_ids=thread_ids,
            stop_event=asyncio.Event(),
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
        await self._request_handler.start_background_task_stream(
            task=task,
            context=context,
            producer=lambda event_queue: self._run_watch(handle=handle, event_queue=event_queue),
        )
        return {"ok": True, "task_id": task_id, "context_id": context_id}

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
        append = False
        metadata = {
            "codex": {
                "thread_lifecycle_watch": {
                    "events": sorted(handle.events),
                    "thread_ids": sorted(handle.thread_ids) if handle.thread_ids else None,
                }
            }
        }
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
