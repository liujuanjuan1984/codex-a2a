from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from codex_a2a.upstream.models import _TurnTracker
from codex_a2a.upstream.notification_mapping import (
    build_tool_call_output_event,
    build_tool_call_state_event,
)

logger = logging.getLogger("codex_a2a.upstream.client")


def normalize_thread_status(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        status_type = value.get("type")
        if isinstance(status_type, str) and status_type.strip():
            return dict(value)
        return None
    if isinstance(value, str) and value.strip():
        return {"type": value.strip()}
    return None


def normalize_thread_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    thread_id = raw_id.strip()
    title_candidates = (
        value.get("name"),
        value.get("title"),
        value.get("preview"),
        thread_id,
    )
    title = thread_id
    for candidate in title_candidates:
        if isinstance(candidate, str) and candidate.strip():
            title = candidate.strip()
            break
    normalized = {
        "id": thread_id,
        "title": title,
        "raw": value,
    }
    status = normalize_thread_status(value.get("status"))
    if status is not None:
        normalized["status"] = status
    return normalized


class CodexStreamEventBridge:
    """Normalize upstream notifications and fan them out to stream consumers."""

    def __init__(self, *, event_queue_maxsize: int) -> None:
        self._event_queue_maxsize = event_queue_maxsize
        self._event_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._turn_trackers: dict[tuple[str, str], _TurnTracker] = {}

    @property
    def event_subscribers(self) -> set[asyncio.Queue[dict[str, Any]]]:
        return self._event_subscribers

    @property
    def turn_trackers(self) -> dict[tuple[str, str], _TurnTracker]:
        return self._turn_trackers

    async def enqueue_stream_event(self, event: dict[str, Any]) -> None:
        if not self._event_subscribers:
            return
        for queue in tuple(self._event_subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Avoid backpressure deadlocks in degraded situations.
                logger.warning("codex event queue full; dropping oldest event")
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

    def get_or_create_tracker(self, thread_id: str, turn_id: str) -> _TurnTracker:
        key = (thread_id, turn_id)
        tracker = self._turn_trackers.get(key)
        if tracker is None:
            tracker = _TurnTracker(thread_id=thread_id, turn_id=turn_id)
            self._turn_trackers[key] = tracker
        return tracker

    async def stream_events(
        self,
        stop_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._event_queue_maxsize)
        self._event_subscribers.add(queue)
        try:
            while True:
                if stop_event and stop_event.is_set():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield event
        finally:
            self._event_subscribers.discard(queue)

    async def handle_notification(
        self,
        message: dict[str, Any],
        *,
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        get_or_create_tracker: Callable[[str, str], _TurnTracker] | None = None,
    ) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str):
            return
        if not isinstance(params, dict):
            params = {}

        emit = enqueue_stream_event or self.enqueue_stream_event
        tracker_factory = get_or_create_tracker or self.get_or_create_tracker

        # v2 stream deltas -> normalized pseudo events consumed by agent.py
        if method == "item/agentMessage/delta":
            thread_id = str(params.get("threadId", "")).strip()
            turn_id = str(params.get("turnId", "")).strip()
            delta = params.get("delta")
            if thread_id and turn_id and isinstance(delta, str):
                tracker = tracker_factory(thread_id, turn_id)
                tracker.text_chunks.append(delta)
                item_id = params.get("itemId")
                if isinstance(item_id, str) and item_id.strip():
                    tracker.message_id = item_id
                await emit(
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "part": {
                                "sessionID": thread_id,
                                "messageID": tracker.message_id or "",
                                "id": tracker.message_id or "",
                                "type": "text",
                                "role": "assistant",
                            },
                            "delta": delta,
                        },
                    }
                )
            return

        if method == "item/reasoning/summaryTextDelta":
            thread_id = str(params.get("threadId", "")).strip()
            delta = params.get("delta")
            item_id = str(params.get("itemId", "")).strip()
            if thread_id and isinstance(delta, str):
                await emit(
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "part": {
                                "sessionID": thread_id,
                                "messageID": item_id,
                                "id": item_id,
                                "type": "reasoning",
                                "role": "assistant",
                            },
                            "delta": delta,
                        },
                    }
                )
            return

        if method in {"item/started", "item/completed"}:
            event = build_tool_call_state_event(params)
            if event is not None:
                await emit(event)
            return

        if method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
            event = build_tool_call_output_event(method, params)
            if event is not None:
                await emit(event)
            return

        if method == "command/exec/outputDelta":
            process_id = str(params.get("processId", "")).strip()
            stream = str(params.get("stream", "")).strip()
            delta_base64 = params.get("deltaBase64")
            if process_id and stream and isinstance(delta_base64, str):
                await emit(
                    {
                        "type": "exec.output.delta",
                        "properties": {
                            "process_id": process_id,
                            "stream": stream,
                            "delta_base64": delta_base64,
                            "cap_reached": bool(params.get("capReached", False)),
                        },
                    }
                )
            return

        if method == "skills/changed":
            await emit(
                {
                    "type": "discovery.skills.changed",
                    "properties": {},
                }
            )
            return

        if method == "app/list/updated":
            raw_items = params.get("data")
            items: list[dict[str, Any]] = []
            if isinstance(raw_items, list):
                for app in raw_items:
                    if not isinstance(app, dict):
                        continue
                    app_id = app.get("id")
                    name = app.get("name")
                    if not isinstance(app_id, str) or not app_id.strip():
                        continue
                    if not isinstance(name, str) or not name.strip():
                        continue
                    items.append(
                        {
                            "id": app_id.strip(),
                            "name": name.strip(),
                            "description": app.get("description"),
                            "is_accessible": bool(app.get("isAccessible", False)),
                            "is_enabled": bool(app.get("isEnabled", False)),
                            "install_url": app.get("installUrl"),
                            "mention_path": f"app://{app_id.strip()}",
                            "branding": app.get("branding"),
                            "labels": app.get("labels"),
                            "codex": {"raw": app},
                        }
                    )
            await emit(
                {
                    "type": "discovery.apps.updated",
                    "properties": {"items": items},
                }
            )
            return

        if method == "thread/started":
            thread = normalize_thread_summary(params.get("thread"))
            if thread is None:
                return
            await emit(
                {
                    "type": "thread.lifecycle.started",
                    "properties": {
                        "thread_id": thread["id"],
                        "thread": thread,
                        "status": thread.get("status"),
                        "source": "thread/started",
                        "codex": {"raw": params},
                    },
                }
            )
            return

        if method == "thread/status/changed":
            thread_id = str(params.get("threadId", "")).strip()
            status = normalize_thread_status(params.get("status"))
            if not thread_id or status is None:
                return
            await emit(
                {
                    "type": "thread.lifecycle.status_changed",
                    "properties": {
                        "thread_id": thread_id,
                        "status": status,
                        "source": "thread/status/changed",
                        "codex": {"raw": params},
                    },
                }
            )
            return

        if method in {"thread/archived", "thread/unarchived", "thread/closed"}:
            thread_id = str(params.get("threadId", "")).strip()
            if not thread_id:
                return
            normalized_type = method.removeprefix("thread/").replace("/", "_")
            await emit(
                {
                    "type": f"thread.lifecycle.{normalized_type}",
                    "properties": {
                        "thread_id": thread_id,
                        "source": method,
                        "codex": {"raw": params},
                    },
                }
            )
            return

        if method == "thread/tokenUsage/updated":
            thread_id = str(params.get("threadId", "")).strip()
            token_usage = params.get("tokenUsage")
            if not thread_id or not isinstance(token_usage, dict):
                return
            last = token_usage.get("last")
            if not isinstance(last, dict):
                return
            await emit(
                {
                    "type": "message.finalized",
                    "properties": {
                        "sessionID": thread_id,
                        "info": {
                            "tokens": {
                                "input": last.get("inputTokens"),
                                "output": last.get("outputTokens"),
                                "total": last.get("totalTokens"),
                                "reasoning": last.get("reasoningOutputTokens"),
                                "cache": {"read": last.get("cachedInputTokens")},
                            }
                        },
                    },
                }
            )
            return

        if method == "turn/started":
            thread_id = str(params.get("threadId", "")).strip()
            turn = params.get("turn")
            if thread_id and isinstance(turn, dict):
                turn_id = str(turn.get("id", "")).strip()
                if turn_id:
                    tracker_factory(thread_id, turn_id)
                    await emit(
                        {
                            "type": "turn.lifecycle.started",
                            "properties": {
                                "thread_id": thread_id,
                                "turn_id": turn_id,
                                "turn": turn,
                                "status": turn.get("status"),
                                "source": "turn/started",
                                "codex": {"raw": params},
                            },
                        }
                    )
            return

        if method == "turn/completed":
            thread_id = str(params.get("threadId", "")).strip()
            turn = params.get("turn")
            if thread_id and isinstance(turn, dict):
                turn_id = str(turn.get("id", "")).strip()
                if turn_id:
                    tracker = tracker_factory(thread_id, turn_id)
                    tracker.raw_turn = turn
                    turn_status = str(turn.get("status", "")).strip()
                    if turn_status.lower() in {"failed", "interrupted", "cancelled", "canceled"}:
                        error = turn.get("error")
                        if isinstance(error, dict):
                            error_message = error.get("message")
                            if isinstance(error_message, str) and error_message.strip():
                                tracker.error = error_message.strip()
                            else:
                                tracker.error = turn_status or "turn failed"
                        else:
                            tracker.error = turn_status or "turn failed"
                    tracker.completed.set()
                    await emit(
                        {
                            "type": "turn.lifecycle.completed",
                            "properties": {
                                "thread_id": thread_id,
                                "turn_id": turn_id,
                                "turn": turn,
                                "status": turn.get("status"),
                                "source": "turn/completed",
                                "codex": {"raw": params},
                            },
                        }
                    )
            return

        if method == "error":
            # Optional mid-turn error notification, preserve for observability only.
            await emit({"type": "codex.error", "properties": {"payload": params}})
