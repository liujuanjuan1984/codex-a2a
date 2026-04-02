from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from codex_a2a.client.client import A2AClient
from codex_a2a.execution.cancellation import (
    await_cancel_cleanup,
    emit_canceled_status,
    prepare_cancel_waitables,
)
from codex_a2a.execution.directory_policy import resolve_and_validate_directory
from codex_a2a.execution.request_metadata import (
    extract_codex_directory,
    extract_shared_session_id,
)
from codex_a2a.execution.response_emitter import (
    emit_non_stream_completion,
    emit_streaming_completion,
)
from codex_a2a.execution.session_runtime import SessionRuntime
from codex_a2a.execution.stream_state import StreamOutputState
from codex_a2a.execution.streaming import consume_codex_stream
from codex_a2a.input_mapping import (
    UnsupportedInputError,
    extract_text_from_normalized_items,
    is_text_only_normalized_input,
    map_a2a_message_parts_to_normalized_items,
    summarize_normalized_items,
)
from codex_a2a.upstream.client import CodexClient

from .output_mapping import enqueue_artifact_update, extract_token_usage, merge_token_usage

if TYPE_CHECKING:
    from codex_a2a.server.runtime_state import SessionStateRepository

logger = logging.getLogger(__name__)


SessionClaimHook = Callable[..., Awaitable[bool]]
SessionFinalizeHook = Callable[..., Awaitable[None]]
SessionOwnerMatcher = Callable[..., Awaitable[bool | None]]


@dataclass(frozen=True)
class SessionGuardBindings:
    session_claim: SessionClaimHook
    session_claim_finalize: SessionFinalizeHook
    session_claim_release: SessionFinalizeHook
    session_owner_matcher: SessionOwnerMatcher


class CodexAgentExecutor(AgentExecutor):
    def __init__(
        self,
        client: CodexClient,
        *,
        streaming_enabled: bool,
        cancel_abort_timeout_seconds: float = 1.0,
        session_cache_ttl_seconds: int = 3600,
        session_cache_maxsize: int = 10_000,
        stream_idle_diagnostic_seconds: float | None = None,
        a2a_client_manager: Any | None = None,
        session_state_store: SessionStateRepository | None = None,
    ) -> None:
        self._client = client
        self._streaming_enabled = streaming_enabled
        self._cancel_abort_timeout_seconds = float(cancel_abort_timeout_seconds)
        self._stream_idle_diagnostic_seconds = stream_idle_diagnostic_seconds
        self._a2a_client_manager = a2a_client_manager
        self._session_runtime = SessionRuntime(
            session_cache_ttl_seconds=session_cache_ttl_seconds,
            session_cache_maxsize=session_cache_maxsize,
            state_store=session_state_store,
        )
        self._session_guard_bindings = SessionGuardBindings(
            session_claim=self._session_runtime.claim_session,
            session_claim_finalize=self._session_runtime.finalize_session_claim,
            session_claim_release=self._session_runtime.release_session_claim,
            session_owner_matcher=self._session_runtime.session_owner_matches,
        )

    @property
    def session_guard_bindings(self) -> SessionGuardBindings:
        return self._session_guard_bindings

    def _resolve_and_validate_directory(self, requested: str | None) -> str | None:
        return resolve_and_validate_directory(self._client, requested)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id
        if not task_id or not context_id:
            await self._emit_error(
                event_queue,
                task_id=task_id or "unknown",
                context_id=context_id or "unknown",
                message="Missing task_id or context_id in request context",
                streaming_request=self._should_stream(context),
            )
            return

        call_context = context.call_context
        identity = (call_context.state.get("identity") if call_context else None) or "anonymous"

        streaming_request = self._should_stream(context)
        message_parts = getattr(context.message, "parts", None) if context.message else None
        try:
            request_input_items = map_a2a_message_parts_to_normalized_items(message_parts)
        except UnsupportedInputError as exc:
            await self._emit_error(
                event_queue,
                task_id=task_id,
                context_id=context_id,
                message=str(exc),
                streaming_request=streaming_request,
            )
            return

        user_text = extract_text_from_normalized_items(request_input_items)
        if not user_text:
            user_text = context.get_user_input().strip()
        session_title = user_text or summarize_normalized_items(request_input_items)
        text_only_request = is_text_only_normalized_input(request_input_items, user_text=user_text)
        bound_session_id = extract_shared_session_id(context)

        # Directory validation
        metadata = context.metadata
        if metadata is not None and not isinstance(metadata, Mapping):
            await self._emit_error(
                event_queue,
                task_id=task_id,
                context_id=context_id,
                message="Invalid metadata: expected an object/map.",
                streaming_request=streaming_request,
            )
            return
        requested_dir = extract_codex_directory(context)

        try:
            directory = self._resolve_and_validate_directory(requested_dir)
        except ValueError as e:
            logger.warning("Directory validation failed: %s", e)
            await self._emit_error(
                event_queue,
                task_id=task_id,
                context_id=context_id,
                message=str(e),
                streaming_request=streaming_request,
            )
            return

        if not user_text and not request_input_items:
            await self._emit_error(
                event_queue,
                task_id=task_id,
                context_id=context_id,
                message="Only text, image file, and codex rich input data parts are supported.",
                streaming_request=streaming_request,
            )
            return

        logger.debug(
            (
                "Received message identity=%s task_id=%s context_id=%s "
                "streaming=%s text=%s part_count=%s"
            ),
            identity,
            task_id,
            context_id,
            streaming_request,
            user_text,
            len(request_input_items),
        )

        stream_artifact_id = f"{task_id}:stream"
        stream_state = StreamOutputState(
            user_text=user_text,
            stable_message_id=f"{task_id}:{context_id}:assistant",
            event_id_namespace=f"{task_id}:{context_id}:{stream_artifact_id}",
        )
        stop_event = asyncio.Event()
        stream_completion_event = asyncio.Event()
        stream_task: asyncio.Task[None] | None = None
        pending_preferred_claim = False
        session_lock: asyncio.Lock | None = None
        session_id = ""
        current_task = asyncio.current_task()
        if current_task is not None:
            await self._session_runtime.track_running_request(
                task_id=task_id,
                context_id=context_id,
                identity=identity,
                task=current_task,
                stop_event=stop_event,
            )

        try:
            session_id, pending_preferred_claim = await self._session_runtime.get_or_create_session(
                identity=identity,
                context_id=context_id,
                title=session_title,
                preferred_session_id=bound_session_id,
                create_session=lambda: self._client.create_session(
                    title=session_title,
                    directory=directory,
                ),
            )
            session_lock = await self._session_runtime.get_session_lock(session_id)
            await session_lock.acquire()
            bind_interrupt_context = getattr(self._client, "bind_interrupt_context", None)
            if callable(bind_interrupt_context):
                bind_interrupt_context(
                    session_id=session_id,
                    identity=identity,
                    task_id=task_id,
                    context_id=context_id,
                )
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.working),
                    final=False,
                )
            )

            next_turn_text = user_text
            next_turn_input_items = (
                None if text_only_request or not request_input_items else list(request_input_items)
            )
            while True:
                send_kwargs: dict[str, Any] = {"directory": directory}
                if next_turn_input_items is not None:
                    send_kwargs["input_items"] = next_turn_input_items
                if streaming_request:
                    stream_completion_event = asyncio.Event()
                    stream_task = asyncio.create_task(
                        consume_codex_stream(
                            client=self._client,
                            session_id=session_id,
                            task_id=task_id,
                            context_id=context_id,
                            artifact_id=stream_artifact_id,
                            stream_state=stream_state,
                            event_queue=event_queue,
                            stop_event=stop_event,
                            completion_event=stream_completion_event,
                            idle_diagnostic_seconds=self._stream_idle_diagnostic_seconds,
                            directory=directory,
                        )
                    )
                    send_kwargs["timeout_override"] = self._client.stream_timeout
                response = await self._client.send_message(
                    session_id,
                    next_turn_text,
                    **send_kwargs,
                )
                next_turn_input_items = None
                if pending_preferred_claim:
                    await self._session_runtime.finalize_preferred_session_binding(
                        identity=identity,
                        context_id=context_id,
                        session_id=session_id,
                    )
                    pending_preferred_claim = False

                response_text = response.text or ""
                tool_results = await self._maybe_handle_tools(response.raw)
                if tool_results:
                    if streaming_request:
                        stream_completion_event.set()
                        if stream_task:
                            await stream_task
                            stream_task = None
                    next_turn_text = self._build_tool_followup_prompt(tool_results)
                    continue

                resolved_message_id = stream_state.resolve_message_id(response.message_id)
                resolved_token_usage = merge_token_usage(
                    extract_token_usage(response.raw),
                    stream_state.token_usage,
                )
                logger.debug(
                    "Codex response task_id=%s session_id=%s message_id=%s text=%s",
                    task_id,
                    response.session_id,
                    resolved_message_id,
                    response_text,
                )
                if streaming_request:
                    stream_completion_event.set()
                    if stream_task:
                        await stream_task
                        stream_task = None
                    await emit_streaming_completion(
                        event_queue=event_queue,
                        task_id=task_id,
                        context_id=context_id,
                        response_text=response_text,
                        session_id=response.session_id,
                        resolved_message_id=resolved_message_id,
                        resolved_token_usage=resolved_token_usage,
                        stream_artifact_id=stream_artifact_id,
                        stream_state=stream_state,
                    )
                else:
                    await emit_non_stream_completion(
                        event_queue=event_queue,
                        context=context,
                        task_id=task_id,
                        context_id=context_id,
                        response_text=response_text,
                        session_id=response.session_id,
                        resolved_message_id=resolved_message_id,
                        resolved_token_usage=resolved_token_usage,
                    )
                break
        except Exception as exc:
            logger.exception("Codex request failed")
            await self._emit_error(
                event_queue,
                task_id=task_id,
                context_id=context_id,
                message=f"Codex error: {exc}",
                streaming_request=streaming_request,
            )
        finally:
            if pending_preferred_claim and session_id:
                with suppress(Exception):
                    await self._session_runtime.release_preferred_session_claim(
                        identity=identity,
                        session_id=session_id,
                    )
            stop_event.set()
            if stream_task:
                stream_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stream_task
            release_interrupt_context = getattr(self._client, "release_interrupt_context", None)
            if callable(release_interrupt_context) and session_id:
                release_interrupt_context(session_id=session_id)
            if session_lock and session_lock.locked():
                session_lock.release()
            await self._session_runtime.untrack_running_request(
                task_id=task_id,
                context_id=context_id,
            )

    async def _maybe_handle_tools(self, raw_response: Any) -> list[dict[str, Any]] | None:
        if not isinstance(raw_response, dict):
            return None

        parts = raw_response.get("parts")
        if not isinstance(parts, list):
            return None

        results: list[dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "tool":
                continue
            if not isinstance(part.get("state"), dict):
                continue
            if part["state"].get("status") != "calling":
                continue
            if part.get("tool") != "a2a_call":
                continue

            result = await self._handle_a2a_call_tool(part)
            if result:
                results.append(result)

        return results if results else None

    async def _handle_a2a_call_tool(self, part: dict[str, Any]) -> dict[str, Any]:
        call_id = str(part.get("callID") or part.get("callId") or uuid.uuid4())
        tool_name = str(part.get("tool") or "a2a_call")
        state = part.get("state", {})
        if not isinstance(state, dict):
            return {"call_id": call_id, "tool": tool_name, "error": "Invalid tool call state"}

        inputs = state.get("input")
        if not isinstance(inputs, dict):
            return {"call_id": call_id, "tool": tool_name, "error": "Invalid input format"}

        agent_url = inputs.get("url")
        message = inputs.get("message")
        if not isinstance(agent_url, str) or not isinstance(message, str):
            return {"call_id": call_id, "tool": tool_name, "error": "Missing url or message"}

        if self._a2a_client_manager is None:
            return {
                "call_id": call_id,
                "tool": tool_name,
                "error": "A2A client manager is not available",
            }

        try:
            client = await self._a2a_client_manager.get_client(agent_url)
            tool_output = ""
            async for event in client.send_message(
                message,
                metadata=part.get("metadata"),
                accepted_output_modes=["text/plain"],
            ):
                text = A2AClient.extract_text(event).strip()
                if text:
                    tool_output = self._merge_streamed_tool_output(tool_output, text)

            if tool_output:
                return {"call_id": call_id, "tool": tool_name, "output": tool_output}
            return {
                "call_id": call_id,
                "tool": tool_name,
                "output": "Task completed.",
            }
        except Exception as exc:
            logger.exception("A2A tool call failed")
            return {"call_id": call_id, "tool": tool_name, "error": str(exc)}

    @staticmethod
    def _build_tool_followup_prompt(tool_results: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for result in tool_results:
            if not isinstance(result, dict):
                continue
            call_id = result.get("call_id")
            tool = result.get("tool") or "tool"
            if result.get("error"):
                parts.append(f"[{tool}#{call_id}] ERROR: {result.get('error')}")
                continue
            output = result.get("output") or result.get("text") or ""
            if output:
                parts.append(f"[{tool}#{call_id}] {output}")
            else:
                parts.append(f"[{tool}#{call_id}] completed")
        return "\n".join(parts)

    @staticmethod
    def _merge_streamed_tool_output(current: str, incoming: str) -> str:
        if not current:
            return incoming
        if not incoming:
            return current
        if incoming == current or incoming in current:
            return current
        if incoming.startswith(current):
            return incoming
        if current.startswith(incoming):
            return current

        separator = (
            ""
            if current.endswith(("\n", " ", "\t")) or incoming.startswith(("\n", " ", "\t"))
            else "\n"
        )
        return f"{current}{separator}{incoming}"

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id
        try:
            if not task_id or not context_id:
                await self._emit_error(
                    event_queue,
                    task_id=task_id or "unknown",
                    context_id=context_id or "unknown",
                    message="Missing task_id or context_id in request context",
                    streaming_request=False,
                )
                return

            call_context = context.call_context
            identity = (call_context.state.get("identity") if call_context else None) or "anonymous"

            await emit_canceled_status(
                event_queue,
                task_id=task_id,
                context_id=context_id,
            )

            running = await self._session_runtime.cancel_running_request(
                task_id=task_id,
                context_id=context_id,
                identity=identity,
            )
            waitables = prepare_cancel_waitables(running, current_task=asyncio.current_task())
            await await_cancel_cleanup(
                waitables,
                task_id=task_id,
                context_id=context_id,
                cancel_abort_timeout_seconds=self._cancel_abort_timeout_seconds,
                logger=logger,
            )
        except Exception as exc:
            logger.exception("Cancel failed")
            if task_id and context_id:
                with suppress(Exception):
                    await self._emit_error(
                        event_queue,
                        task_id=task_id,
                        context_id=context_id,
                        message=f"Cancel failed: {exc}",
                        streaming_request=False,
                    )

    async def _emit_error(
        self,
        event_queue: EventQueue,
        task_id: str,
        context_id: str,
        message: str,
        *,
        streaming_request: bool,
    ) -> None:
        error_message = Message(
            message_id=str(uuid.uuid4()),
            role=Role.agent,
            parts=[Part(root=TextPart(text=message))],
            task_id=task_id,
            context_id=context_id,
        )
        if streaming_request:
            await enqueue_artifact_update(
                event_queue=event_queue,
                task_id=task_id,
                context_id=context_id,
                artifact_id=f"{task_id}:error",
                part=TextPart(text=message),
                append=False,
                last_chunk=True,
            )
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.failed),
                    final=True,
                )
            )
            return
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.failed, message=error_message),
            history=[error_message],
        )
        await event_queue.enqueue_event(task)

    def _should_stream(self, context: RequestContext) -> bool:
        if not self._streaming_enabled:
            return False
        call_context = context.call_context
        if not call_context:
            return False
        if call_context.state.get("a2a_streaming_request"):
            return True
        # JSON-RPC transport sets method in call context state.
        method = call_context.state.get("method")
        return method == "message/stream"
