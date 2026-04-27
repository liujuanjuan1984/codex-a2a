from __future__ import annotations

import uuid
from typing import Any

from a2a.server.agent_execution import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import Artifact, Task, TaskState, TaskStatus, TaskStatusUpdateEvent

from codex_a2a.a2a_proto import new_text_part
from codex_a2a.contracts.runtime_output import (
    build_output_metadata,
    build_status_stream_metadata,
)
from codex_a2a.execution.output_mapping import (
    build_assistant_message,
    build_history,
    enqueue_artifact_update,
)
from codex_a2a.execution.stream_state import (
    BlockType,
    StreamOutputState,
    build_stream_artifact_metadata,
)


async def emit_initial_task(
    *,
    event_queue: EventQueue,
    task_id: str,
    context_id: str,
) -> None:
    await event_queue.enqueue_event(
        Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
    )


async def emit_streaming_completion(
    *,
    event_queue: EventQueue,
    task_id: str,
    context_id: str,
    response_text: str,
    session_id: str,
    resolved_message_id: str,
    resolved_token_usage: dict[str, Any] | None,
    stream_artifact_id: str,
    stream_state: StreamOutputState,
) -> None:
    if stream_state.should_emit_final_snapshot(response_text):
        sequence = stream_state.next_sequence()
        await enqueue_artifact_update(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
            artifact_id=stream_artifact_id,
            part=new_text_part(response_text),
            append=stream_state.emitted_stream_chunk,
            last_chunk=True,
            artifact_metadata=build_stream_artifact_metadata(
                block_type=BlockType.TEXT,
                source="final_snapshot",
                message_id=resolved_message_id,
                sequence=sequence,
                event_id=stream_state.build_event_id(sequence),
            ),
        )
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            metadata=build_output_metadata(
                session_id=session_id,
                usage=resolved_token_usage,
                stream=build_status_stream_metadata(
                    message_id=resolved_message_id,
                    event_id=f"{stream_state.event_id_namespace}:status",
                    source="status",
                ),
            ),
        )
    )


async def emit_non_stream_completion(
    *,
    event_queue: EventQueue,
    context: RequestContext,
    task_id: str,
    context_id: str,
    response_text: str,
    session_id: str,
    resolved_message_id: str,
    resolved_token_usage: dict[str, Any] | None,
) -> None:
    normalized_text = response_text or "(No text content returned by Codex.)"
    assistant_message = build_assistant_message(
        task_id=task_id,
        context_id=context_id,
        text=normalized_text,
        message_id=resolved_message_id,
    )
    artifact = Artifact(
        artifact_id=str(uuid.uuid4()),
        name="response",
        parts=[new_text_part(normalized_text)],
    )
    task = Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(
            state=TaskState.TASK_STATE_COMPLETED,
            message=assistant_message,
        ),
        history=build_history(context),
        artifacts=[artifact],
        metadata=build_output_metadata(
            session_id=session_id,
            usage=resolved_token_usage,
        ),
    )
    await event_queue.enqueue_event(task)
