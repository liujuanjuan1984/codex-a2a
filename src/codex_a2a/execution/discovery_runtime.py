from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.types import DataPart, Task, TaskState, TaskStatus

from codex_a2a.execution.output_mapping import build_assistant_message, enqueue_artifact_update

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

    from codex_a2a.server.request_handler import CodexRequestHandler
    from codex_a2a.upstream.client import CodexClient


SUPPORTED_DISCOVERY_EVENTS = frozenset({"skills.changed", "apps.updated"})


@dataclass(slots=True)
class DiscoveryWatchHandle:
    task_id: str
    context_id: str
    events: frozenset[str]
    stop_event: asyncio.Event


class CodexDiscoveryRuntime:
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
        task_id = str(uuid.uuid4())
        context_id = task_id
        handle = DiscoveryWatchHandle(
            task_id=task_id,
            context_id=context_id,
            events=events,
            stop_event=asyncio.Event(),
        )
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(
                state=TaskState.working,
                message=build_assistant_message(
                    task_id,
                    context_id,
                    (
                        "Started Codex discovery watch. Subscribe with "
                        "tasks/resubscribe to receive invalidation and "
                        "refresh signals."
                    ),
                    message_id=f"{task_id}:status:started",
                ),
            ),
            metadata={
                "codex": {
                    "discovery_watch": {
                        "events": sorted(events),
                    }
                }
            },
        )
        await self._request_handler.start_background_task_stream(
            task=task,
            context=context,
            producer=lambda event_queue: self._run_watch(handle=handle, event_queue=event_queue),
        )
        return {"ok": True, "task_id": task_id, "context_id": context_id}

    def _normalize_events(self, request: dict[str, Any] | None) -> frozenset[str]:
        if not isinstance(request, dict):
            return SUPPORTED_DISCOVERY_EVENTS
        raw_events = request.get("events")
        if raw_events is None:
            return SUPPORTED_DISCOVERY_EVENTS
        if not isinstance(raw_events, list) or not raw_events:
            raise ValueError("request.events must be a non-empty array")
        events: set[str] = set()
        for item in raw_events:
            if not isinstance(item, str) or item not in SUPPORTED_DISCOVERY_EVENTS:
                allowed = ", ".join(sorted(SUPPORTED_DISCOVERY_EVENTS))
                raise ValueError(f"request.events entries must be one of: {allowed}")
            events.add(item)
        return frozenset(events)

    async def _run_watch(self, *, handle: DiscoveryWatchHandle, event_queue) -> None:  # noqa: ANN001
        append = False
        async for event in self._client.stream_events(stop_event=handle.stop_event):
            payload = self._payload_from_event(event, events=handle.events)
            if payload is None:
                continue
            await enqueue_artifact_update(
                event_queue=event_queue,
                task_id=handle.task_id,
                context_id=handle.context_id,
                artifact_id=f"{handle.task_id}:discovery",
                part=DataPart(data=payload),
                append=append,
                last_chunk=None,
                artifact_metadata={"codex": {"discovery_watch": {"events": sorted(handle.events)}}},
                event_metadata={"codex": {"discovery_watch": {"events": sorted(handle.events)}}},
            )
            append = True

    def _payload_from_event(
        self,
        event: dict[str, Any],
        *,
        events: frozenset[str],
    ) -> dict[str, Any] | None:
        event_type = event.get("type")
        properties = event.get("properties")
        if event_type == "discovery.skills.changed" and "skills.changed" in events:
            return {
                "kind": "skills_changed",
                "event": "skills.changed",
                "source": "skills/changed",
            }
        if (
            event_type == "discovery.apps.updated"
            and "apps.updated" in events
            and isinstance(properties, dict)
        ):
            return {
                "kind": "apps_updated",
                "event": "apps.updated",
                "source": "app/list/updated",
                "items": properties.get("items", []),
            }
        return None
