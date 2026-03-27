from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus, TaskStatusUpdateEvent, TextPart

from codex_a2a.contracts.runtime_output import build_status_stream_metadata
from codex_a2a.execution.output_mapping import enqueue_artifact_update
from codex_a2a.execution.stream_state import BlockType, build_stream_artifact_metadata
from codex_a2a.upstream.request_mapping import format_exec_result_text

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

    from codex_a2a.server.request_handler import CodexRequestHandler
    from codex_a2a.upstream.client import CodexClient


@dataclass(slots=True)
class ExecSessionHandle:
    process_id: str
    task_id: str
    context_id: str
    stop_event: asyncio.Event
    command_text: str
    terminate_requested: bool = False
    producer_task: asyncio.Task[None] | None = None


class CodexExecRuntime:
    def __init__(
        self,
        *,
        client: CodexClient,
        request_handler: CodexRequestHandler,
    ) -> None:
        self._client = client
        self._request_handler = request_handler
        self._lock = asyncio.Lock()
        self._sessions: dict[str, ExecSessionHandle] = {}

    async def start(
        self,
        *,
        request: dict[str, Any],
        directory: str | None,
        context: ServerCallContext | None,
    ) -> dict[str, Any]:
        process_id = str(request.get("processId") or "").strip() or f"exec-{uuid.uuid4().hex}"
        task_id = str(uuid.uuid4())
        context_id = task_id
        command_text = self._build_command_text(request)
        handle = ExecSessionHandle(
            process_id=process_id,
            task_id=task_id,
            context_id=context_id,
            stop_event=asyncio.Event(),
            command_text=command_text,
        )
        async with self._lock:
            if process_id in self._sessions:
                raise ValueError("request.process_id must be unique among active exec sessions")
            self._sessions[process_id] = handle

        initial_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(
                state=TaskState.working,
                message=self._build_status_message(
                    task_id=task_id,
                    context_id=context_id,
                    text=f"Started interactive exec session: {command_text}",
                    message_id=f"{task_id}:status:started",
                ),
            ),
            metadata=self._build_exec_metadata(
                process_id=process_id,
                command_text=command_text,
                phase="running",
                tty=bool(request.get("tty", True)),
            ),
        )

        producer_task = await self._request_handler.start_background_task_stream(
            task=initial_task,
            context=context,
            producer=lambda event_queue: self._run_exec_session(
                handle=handle,
                request=request,
                directory=directory,
                event_queue=event_queue,
            ),
        )
        handle.producer_task = producer_task
        producer_task.add_done_callback(
            lambda _: asyncio.create_task(self._remove_session(process_id))
        )
        return {
            "ok": True,
            "task_id": task_id,
            "context_id": context_id,
            "process_id": process_id,
        }

    async def write(
        self,
        *,
        process_id: str,
        delta_base64: str | None,
        close_stdin: bool | None,
    ) -> dict[str, Any]:
        handle = await self._require_session(process_id)
        await self._client.exec_write(
            process_id=handle.process_id,
            delta_base64=delta_base64,
            close_stdin=close_stdin,
        )
        return {"ok": True, "process_id": handle.process_id}

    async def resize(
        self,
        *,
        process_id: str,
        rows: int,
        cols: int,
    ) -> dict[str, Any]:
        handle = await self._require_session(process_id)
        await self._client.exec_resize(process_id=handle.process_id, rows=rows, cols=cols)
        return {"ok": True, "process_id": handle.process_id}

    async def terminate(
        self,
        *,
        process_id: str,
    ) -> dict[str, Any]:
        handle = await self._require_session(process_id)
        handle.terminate_requested = True
        await self._client.exec_terminate(process_id=handle.process_id)
        return {"ok": True, "process_id": handle.process_id}

    async def _remove_session(self, process_id: str) -> None:
        async with self._lock:
            self._sessions.pop(process_id, None)

    async def _require_session(self, process_id: str) -> ExecSessionHandle:
        async with self._lock:
            handle = self._sessions.get(process_id)
        if handle is None:
            raise LookupError(f"Unknown exec session: {process_id}")
        return handle

    async def _run_exec_session(
        self,
        *,
        handle: ExecSessionHandle,
        request: dict[str, Any],
        directory: str | None,
        event_queue,
    ) -> None:
        stream_artifact_ids = {
            "stdout": f"{handle.task_id}:exec:stdout",
            "stderr": f"{handle.task_id}:exec:stderr",
        }
        stream_append_seen: dict[str, bool] = {"stdout": False, "stderr": False}
        sequence = 0
        pending_event_task: asyncio.Task[dict[str, Any]] | None = None
        stream_iter = self._client.stream_events(stop_event=handle.stop_event, directory=directory)
        exec_task = asyncio.create_task(
            self._client.exec_start(
                request,
                directory=directory,
                timeout_override=self._client.stream_timeout,
            )
        )
        exec_task.set_name(f"codex_exec_start:{handle.process_id}")

        try:
            while True:
                if pending_event_task is None:
                    pending_event_task = asyncio.create_task(
                        self._next_stream_event(stream_iter)
                    )
                done, _ = await asyncio.wait(
                    {exec_task, pending_event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if pending_event_task in done:
                    try:
                        event = pending_event_task.result()
                    except StopAsyncIteration:
                        pending_event_task = None
                    else:
                        pending_event_task = None
                        if (
                            event.get("type") == "exec.output.delta"
                            and event.get("properties", {}).get("process_id") == handle.process_id
                        ):
                            sequence += 1
                            await self._emit_output_delta(
                                event_queue=event_queue,
                                task_id=handle.task_id,
                                context_id=handle.context_id,
                                artifact_id=stream_artifact_ids[
                                    str(event["properties"].get("stream", "stdout"))
                                ],
                                props=event["properties"],
                                append=stream_append_seen,
                                sequence=sequence,
                            )
                if exec_task in done:
                    result = exec_task.result()
                    await self._emit_terminal_status(
                        event_queue=event_queue,
                        handle=handle,
                        result=result,
                    )
                    break
        except asyncio.CancelledError:
            handle.stop_event.set()
            with contextlib.suppress(Exception):
                await self._client.exec_terminate(process_id=handle.process_id)
            raise
        except Exception as exc:
            logger.exception("Interactive exec session failed process_id=%s", handle.process_id)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=handle.task_id,
                    context_id=handle.context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=self._build_status_message(
                            task_id=handle.task_id,
                            context_id=handle.context_id,
                            text=f"Interactive exec failed: {exc}",
                            message_id=f"{handle.task_id}:status:failed",
                        ),
                    ),
                    final=True,
                    metadata=self._build_exec_metadata(
                        process_id=handle.process_id,
                        command_text=handle.command_text,
                        phase="failed",
                        error=str(exc),
                    ),
                )
            )
        finally:
            handle.stop_event.set()
            if pending_event_task is not None:
                pending_event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending_event_task

    @staticmethod
    async def _next_stream_event(stream_iter) -> dict[str, Any]:  # noqa: ANN001
        return await anext(stream_iter)

    async def _emit_output_delta(
        self,
        *,
        event_queue,
        task_id: str,
        context_id: str,
        artifact_id: str,
        props: dict[str, Any],
        append: dict[str, bool],
        sequence: int,
    ) -> None:
        stream = str(props.get("stream", "stdout"))
        delta_base64 = str(props.get("delta_base64", ""))
        await enqueue_artifact_update(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
            artifact_id=artifact_id,
            part=TextPart(text=self._decode_delta_text(delta_base64)),
            append=append.get(stream, False),
            last_chunk=bool(props.get("cap_reached", False)),
            artifact_metadata=build_stream_artifact_metadata(
                block_type=BlockType.TEXT,
                source="codex.exec.output_delta",
                message_id=f"{task_id}:exec:{stream}",
                sequence=sequence,
                event_id=f"{task_id}:exec:{sequence}",
            ),
            event_metadata={
                "codex": {
                    "exec": {
                        "stream": stream,
                        "delta_base64": delta_base64,
                        "cap_reached": bool(props.get("cap_reached", False)),
                    }
                }
            },
        )
        append[stream] = True

    async def _emit_terminal_status(
        self,
        *,
        event_queue,
        handle: ExecSessionHandle,
        result: dict[str, Any],
    ) -> None:
        exit_code = result.get("exitCode")
        final_state = TaskState.completed
        phase = "completed"
        if handle.terminate_requested:
            final_state = TaskState.canceled
            phase = "terminated"
        elif exit_code not in {0, None}:
            final_state = TaskState.failed
            phase = "failed"
        summary = format_exec_result_text(result)
        await enqueue_artifact_update(
            event_queue=event_queue,
            task_id=handle.task_id,
            context_id=handle.context_id,
            artifact_id=f"{handle.task_id}:exec:result",
            part=TextPart(text=summary),
            append=False,
            last_chunk=True,
            artifact_metadata=build_stream_artifact_metadata(
                block_type=BlockType.TEXT,
                source="codex.exec.result",
                message_id=f"{handle.task_id}:exec:result",
                sequence=None,
                event_id=f"{handle.task_id}:exec:result",
            ),
            event_metadata={
                "codex": {
                    "exec": {
                        "process_id": handle.process_id,
                        "exit_code": exit_code,
                        "terminated": handle.terminate_requested,
                    }
                }
            },
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=handle.task_id,
                context_id=handle.context_id,
                status=TaskStatus(
                    state=final_state,
                    message=self._build_status_message(
                        task_id=handle.task_id,
                        context_id=handle.context_id,
                        text=summary,
                        message_id=f"{handle.task_id}:status:{phase}",
                    ),
                ),
                final=True,
                metadata=self._build_exec_metadata(
                    process_id=handle.process_id,
                    command_text=handle.command_text,
                    phase=phase,
                    exit_code=exit_code,
                    terminated=handle.terminate_requested,
                    stream=build_status_stream_metadata(
                        source="codex.exec.status",
                        message_id=f"{handle.task_id}:exec:result",
                        event_id=f"{handle.task_id}:status:{phase}",
                    ),
                ),
            )
        )

    def _build_exec_metadata(
        self,
        *,
        process_id: str,
        command_text: str,
        phase: str,
        tty: bool | None = None,
        exit_code: int | None = None,
        terminated: bool | None = None,
        error: str | None = None,
        stream: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        exec_metadata: dict[str, Any] = {
            "process_id": process_id,
            "command": command_text,
            "phase": phase,
        }
        if tty is not None:
            exec_metadata["tty"] = tty
        if exit_code is not None:
            exec_metadata["exit_code"] = exit_code
        if terminated is not None:
            exec_metadata["terminated"] = terminated
        if error is not None:
            exec_metadata["error"] = error
        metadata: dict[str, Any] = {"codex": {"exec": exec_metadata}}
        if stream is not None:
            metadata.setdefault("shared", {})["stream"] = stream
        return metadata

    @staticmethod
    def _decode_delta_text(delta_base64: str) -> str:
        try:
            decoded = base64.b64decode(delta_base64, validate=True)
        except (binascii.Error, ValueError):
            return ""
        return decoded.decode("utf-8", errors="replace")

    @staticmethod
    def _build_command_text(request: dict[str, Any]) -> str:
        command = str(request.get("command", "")).strip()
        arguments = str(request.get("arguments") or "").strip()
        if not arguments:
            return command
        return f"{command} {arguments}"

    @staticmethod
    def _build_status_message(
        *,
        task_id: str,
        context_id: str,
        text: str,
        message_id: str,
    ) -> Message:
        return Message(
            message_id=message_id,
            role=Role.agent,
            parts=[Part(root=TextPart(text=text))],
            task_id=task_id,
            context_id=context_id,
        )
