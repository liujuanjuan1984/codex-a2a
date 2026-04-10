from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.types import DataPart, Task, TaskState, TaskStatus, TaskStatusUpdateEvent

from codex_a2a.contracts.extensions import REVIEW_CONTROL_SUPPORTED_EVENTS
from codex_a2a.execution.output_mapping import build_assistant_message, enqueue_artifact_update
from codex_a2a.execution.watch_events import normalize_watch_event_filter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

    from codex_a2a.server.request_handler import CodexRequestHandler
    from codex_a2a.upstream.client import CodexClient


_REVIEW_FAILED_TURN_STATUSES = {"failed", "interrupted", "cancelled", "canceled"}


@dataclass(slots=True)
class ReviewWatchHandle:
    task_id: str
    context_id: str
    source_thread_id: str
    review_thread_id: str
    turn_id: str
    events: frozenset[str]
    stop_event: asyncio.Event


class CodexReviewRuntime:
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
        thread_id: str,
        review_thread_id: str,
        turn_id: str,
        request: dict[str, Any] | None,
        context: ServerCallContext | None,
    ) -> dict[str, Any]:
        events = normalize_watch_event_filter(
            request,
            supported_events=REVIEW_CONTROL_SUPPORTED_EVENTS,
        )
        task_id = str(uuid.uuid4())
        context_id = task_id
        handle = ReviewWatchHandle(
            task_id=task_id,
            context_id=context_id,
            source_thread_id=thread_id,
            review_thread_id=review_thread_id,
            turn_id=turn_id,
            events=events,
            stop_event=asyncio.Event(),
        )
        metadata = {
            "codex": {
                "review_watch": {
                    "thread_id": thread_id,
                    "review_thread_id": review_thread_id,
                    "turn_id": turn_id,
                    "events": sorted(events),
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
                        "Started Codex review watch. Subscribe with tasks/resubscribe "
                        "to receive review lifecycle signals."
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

    async def _run_watch(self, *, handle: ReviewWatchHandle, event_queue) -> None:  # noqa: ANN001
        append = False
        metadata = {
            "codex": {
                "review_watch": {
                    "thread_id": handle.source_thread_id,
                    "review_thread_id": handle.review_thread_id,
                    "turn_id": handle.turn_id,
                    "events": sorted(handle.events),
                }
            }
        }

        started_payload = self._started_payload(handle)
        if started_payload is not None:
            await enqueue_artifact_update(
                event_queue=event_queue,
                task_id=handle.task_id,
                context_id=handle.context_id,
                artifact_id=f"{handle.task_id}:review-watch",
                part=DataPart(data=started_payload),
                append=False,
                last_chunk=None,
                artifact_metadata=metadata,
                event_metadata=metadata,
            )
            append = True

        async for event in self._client.stream_events(stop_event=handle.stop_event):
            payload = self._payload_from_event(event, handle=handle)
            if payload is None:
                continue
            is_terminal = payload["event"] in {"review.completed", "review.failed"}
            await enqueue_artifact_update(
                event_queue=event_queue,
                task_id=handle.task_id,
                context_id=handle.context_id,
                artifact_id=f"{handle.task_id}:review-watch",
                part=DataPart(data=payload),
                append=append,
                last_chunk=is_terminal,
                artifact_metadata=metadata,
                event_metadata=metadata,
            )
            append = True
            if is_terminal:
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        task_id=handle.task_id,
                        context_id=handle.context_id,
                        status=TaskStatus(
                            state=(
                                TaskState.completed
                                if payload["event"] == "review.completed"
                                else TaskState.failed
                            ),
                            message=build_assistant_message(
                                handle.task_id,
                                handle.context_id,
                                (
                                    "Review completed."
                                    if payload["event"] == "review.completed"
                                    else "Review failed."
                                ),
                                message_id=(
                                    f"{handle.task_id}:status:completed"
                                    if payload["event"] == "review.completed"
                                    else f"{handle.task_id}:status:failed"
                                ),
                            ),
                        ),
                        final=True,
                        metadata=metadata,
                    )
                )
                break

    def _started_payload(self, handle: ReviewWatchHandle) -> dict[str, Any] | None:
        if "review.started" not in handle.events:
            return None
        return {
            "kind": "review_started",
            "event": "review.started",
            "thread_id": handle.source_thread_id,
            "review_thread_id": handle.review_thread_id,
            "turn_id": handle.turn_id,
            "status": "inProgress",
            "source": "review/start",
        }

    def _payload_from_event(
        self,
        event: dict[str, Any],
        *,
        handle: ReviewWatchHandle,
    ) -> dict[str, Any] | None:
        event_type = event.get("type")
        properties = event.get("properties")
        if not isinstance(event_type, str) or not isinstance(properties, dict):
            return None

        if event_type == "thread.lifecycle.status_changed":
            if "review.status.changed" not in handle.events:
                return None
            thread_id = properties.get("thread_id")
            if thread_id != handle.review_thread_id:
                return None
            return {
                "kind": "review_status_changed",
                "event": "review.status.changed",
                "thread_id": handle.source_thread_id,
                "review_thread_id": handle.review_thread_id,
                "turn_id": handle.turn_id,
                "status": properties.get("status"),
                "source": properties.get("source"),
                **(
                    {"codex": properties["codex"]}
                    if isinstance(properties.get("codex"), dict)
                    else {}
                ),
            }

        if event_type != "turn.lifecycle.completed":
            return None
        turn_id = properties.get("turn_id")
        thread_id = properties.get("thread_id")
        if turn_id != handle.turn_id or thread_id != handle.review_thread_id:
            return None

        review = properties.get("turn")
        if not isinstance(review, dict):
            return None
        turn_status = str(review.get("status", "")).strip()
        event_name = (
            "review.failed"
            if turn_status.lower() in _REVIEW_FAILED_TURN_STATUSES
            else "review.completed"
        )
        if event_name not in handle.events:
            return None
        payload: dict[str, Any] = {
            "kind": "review_failed" if event_name == "review.failed" else "review_completed",
            "event": event_name,
            "thread_id": handle.source_thread_id,
            "review_thread_id": handle.review_thread_id,
            "turn_id": handle.turn_id,
            "status": review.get("status"),
            "source": properties.get("source"),
            "review": review,
        }
        codex_private = properties.get("codex")
        if isinstance(codex_private, dict):
            payload["codex"] = codex_private
        return payload
