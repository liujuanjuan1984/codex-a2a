from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.input_mapping import build_turn_input_from_normalized_items
from codex_a2a.upstream.models import CodexMessage, _TurnTracker
from codex_a2a.upstream.request_mapping import (
    apply_thread_start_execution_options,
    apply_turn_start_execution_options,
    build_shell_exec_params,
    coerce_request_execution_options,
    convert_request_parts_to_turn_input,
    format_shell_response,
    uuid_like_suffix,
)
from codex_a2a.upstream.stream_bridge import normalize_thread_summary


class CodexConversationFacade:
    """Own thread/session/message RPC mappings while keeping the client API stable."""

    def __init__(
        self,
        *,
        workspace_root: str | None,
        model_id: str | None,
        rpc_request: Callable[..., Awaitable[Any]],
        get_or_create_tracker: Callable[[str, str], _TurnTracker],
        turn_trackers: dict[tuple[str, str], _TurnTracker],
    ) -> None:
        self._workspace_root = workspace_root
        self._model_id = model_id
        self._rpc_request = rpc_request
        self._get_or_create_tracker = get_or_create_tracker
        self._turn_trackers = turn_trackers

    async def create_session(
        self,
        title: str | None = None,
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> str:
        params: dict[str, Any] = {}
        normalized_title = title.strip() if title else ""
        if normalized_title:
            params["name"] = normalized_title
        if directory:
            params["cwd"] = directory
        elif self._workspace_root:
            params["cwd"] = self._workspace_root
        apply_thread_start_execution_options(
            params,
            execution_options=coerce_request_execution_options(execution_options),
            default_model_id=self._model_id,
        )
        result = await self._rpc_request("thread/start", params)
        if not isinstance(result, dict):
            raise RuntimeError("codex thread/start response missing result object")
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError("codex thread/start response missing thread")
        session_id = thread.get("id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise RuntimeError("codex thread/start response missing thread id")
        return session_id.strip()

    async def list_sessions(self, *, query: dict[str, Any]) -> list[dict[str, Any]]:
        rpc_params: dict[str, Any] = {}
        if "limit" in query:
            with contextlib.suppress(ValueError):
                rpc_params["limit"] = int(query["limit"])
        result = await self._rpc_request("thread/list", rpc_params)
        if not isinstance(result, dict):
            return []
        data = result.get("data")
        if not isinstance(data, list):
            return []
        sessions: list[dict[str, Any]] = []
        for item in data:
            session = normalize_thread_summary(item)
            if session is None:
                continue
            sessions.append(session)
        return sessions

    async def thread_fork(self, thread_id: str, *, params: dict[str, Any] | None = None) -> Any:
        result = await self._rpc_request(
            "thread/fork",
            self._merge_thread_params(thread_id, params),
        )
        if not isinstance(result, dict):
            raise RuntimeError("codex thread/fork response missing result object")
        thread = normalize_thread_summary(result.get("thread"))
        if thread is None:
            raise RuntimeError("codex thread/fork response missing thread")
        return thread

    async def thread_archive(self, thread_id: str) -> None:
        await self._rpc_request("thread/archive", {"threadId": thread_id})

    async def thread_unsubscribe(self, thread_id: str) -> None:
        await self._rpc_request("thread/unsubscribe", {"threadId": thread_id})

    async def thread_unarchive(self, thread_id: str) -> Any:
        result = await self._rpc_request("thread/unarchive", {"threadId": thread_id})
        if not isinstance(result, dict):
            raise RuntimeError("codex thread/unarchive response missing result object")
        thread = normalize_thread_summary(result.get("thread"))
        if thread is None:
            raise RuntimeError("codex thread/unarchive response missing thread")
        return thread

    async def thread_metadata_update(
        self,
        thread_id: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        result = await self._rpc_request(
            "thread/metadata/update",
            self._merge_thread_params(thread_id, params),
        )
        if not isinstance(result, dict):
            raise RuntimeError("codex thread/metadata/update response missing result object")
        thread = normalize_thread_summary(result.get("thread"))
        if thread is None:
            raise RuntimeError("codex thread/metadata/update response missing thread")
        return thread

    async def list_messages(
        self,
        session_id: str,
        *,
        query: dict[str, Any],
    ) -> list[dict[str, Any]]:
        limit: int | None = None
        if "limit" in query:
            with contextlib.suppress(ValueError):
                limit = int(query["limit"])
        result = await self._rpc_request(
            "thread/read",
            {"threadId": session_id, "includeTurns": True},
        )
        if not isinstance(result, dict):
            return []
        thread = result.get("thread")
        if not isinstance(thread, dict):
            return []
        turns = thread.get("turns")
        if not isinstance(turns, list):
            return []

        messages: list[dict[str, Any]] = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            items = turn.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type", "")).lower()
                if item_type not in {"usermessage", "agentmessage"}:
                    continue
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id:
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    text = ""
                role = "assistant" if item_type == "agentmessage" else "user"
                messages.append(
                    {
                        "info": {"id": item_id, "role": role},
                        "parts": [{"type": "text", "text": text}],
                        "raw": item,
                    }
                )
        if limit is not None:
            messages = messages[-limit:]
        return messages

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        input_items: list[dict[str, Any]] | None = None,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
        timeout_seconds: float | None,
    ) -> CodexMessage:
        input_payload = (
            build_turn_input_from_normalized_items(input_items)
            if input_items is not None
            else [{"type": "text", "text": text, "text_elements": []}]
        )

        params: dict[str, Any] = {
            "threadId": session_id,
            "input": input_payload,
        }
        if directory:
            params["cwd"] = directory
        elif self._workspace_root:
            params["cwd"] = self._workspace_root
        apply_turn_start_execution_options(
            params,
            execution_options=coerce_request_execution_options(execution_options),
            default_model_id=self._model_id,
        )

        result = await self._rpc_request("turn/start", params)
        if not isinstance(result, dict):
            raise RuntimeError("codex turn/start response missing result object")
        turn = result.get("turn")
        if not isinstance(turn, dict):
            raise RuntimeError("codex turn/start response missing turn")
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise RuntimeError("codex turn/start response missing turn id")

        turn_id = turn_id.strip()
        tracker_key = (session_id, turn_id)
        tracker = self._get_or_create_tracker(session_id, turn_id)
        try:
            if timeout_seconds is None:
                await tracker.completed.wait()
            else:
                await asyncio.wait_for(tracker.completed.wait(), timeout=timeout_seconds)
            if tracker.error:
                raise RuntimeError(f"codex turn failed: {tracker.error}")
            return CodexMessage(
                text=tracker.text,
                session_id=session_id,
                message_id=tracker.message_id,
                raw={"turn": tracker.raw_turn or turn},
            )
        except TimeoutError as exc:
            raise RuntimeError("codex turn did not complete before timeout") from exc
        finally:
            self._turn_trackers.pop(tracker_key, None)

    async def session_prompt_async(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": session_id,
            "input": convert_request_parts_to_turn_input(request),
        }
        if directory:
            params["cwd"] = directory
        elif self._workspace_root:
            params["cwd"] = self._workspace_root
        apply_turn_start_execution_options(
            params,
            execution_options=coerce_request_execution_options(execution_options),
            default_model_id=self._model_id,
        )
        result = await self._rpc_request("turn/start", params)
        if not isinstance(result, dict):
            raise RuntimeError("codex turn/start response missing result object")
        turn = result.get("turn")
        if not isinstance(turn, dict):
            raise RuntimeError("codex turn/start response missing turn")
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise RuntimeError("codex turn/start response missing turn id")
        return {"ok": True, "session_id": session_id, "turn_id": turn_id.strip()}

    async def turn_steer(
        self,
        thread_id: str,
        *,
        expected_turn_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._rpc_request(
            "turn/steer",
            {
                "threadId": thread_id,
                "input": convert_request_parts_to_turn_input(request),
                "expectedTurnId": expected_turn_id,
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError("codex turn/steer response missing result object")
        turn_id = result.get("turnId")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise RuntimeError("codex turn/steer response missing turn id")
        return {"ok": True, "thread_id": thread_id, "turn_id": turn_id.strip()}

    async def review_start(
        self,
        thread_id: str,
        *,
        target: dict[str, Any],
        delivery: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "target": target}
        if delivery is not None:
            params["delivery"] = delivery
        result = await self._rpc_request("review/start", params)
        if not isinstance(result, dict):
            raise RuntimeError("codex review/start response missing result object")
        turn = result.get("turn")
        if not isinstance(turn, dict):
            raise RuntimeError("codex review/start response missing turn")
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise RuntimeError("codex review/start response missing turn id")
        review_thread_id = result.get("reviewThreadId")
        if delivery != "detached" and (
            not isinstance(review_thread_id, str) or not review_thread_id.strip()
        ):
            review_thread_id = thread_id
        if not isinstance(review_thread_id, str) or not review_thread_id.strip():
            raise RuntimeError("codex review/start response missing review thread id")
        return {
            "ok": True,
            "turn_id": turn_id.strip(),
            "review_thread_id": review_thread_id.strip(),
        }

    async def session_command(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
        timeout_seconds: float | None,
    ) -> CodexMessage:
        command = str(request["command"]).strip()
        arguments = str(request.get("arguments", "")).strip()
        prompt = f"/{command}" if not arguments else f"/{command} {arguments}"
        return await self.send_message(
            session_id,
            prompt,
            directory=directory,
            execution_options=execution_options,
            timeout_seconds=timeout_seconds,
        )

    async def session_shell(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
    ) -> dict[str, Any]:
        command_text = str(request["command"]).strip()
        if not command_text:
            raise RuntimeError("shell command must not be empty")
        result = await self._rpc_request(
            "command/exec",
            build_shell_exec_params(
                command_text=command_text,
                directory=directory,
                default_workspace_root=self._workspace_root,
            ),
        )
        if not isinstance(result, dict):
            raise RuntimeError("codex command/exec response missing result object")
        return {
            "info": {
                "id": f"shell:{session_id}:{uuid_like_suffix(command_text)}",
                "role": "assistant",
            },
            "parts": [
                {
                    "type": "text",
                    "text": format_shell_response(result),
                }
            ],
            "raw": result,
        }

    @staticmethod
    def _merge_thread_params(
        thread_id: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        rpc_params: dict[str, Any] = {"threadId": thread_id}
        if isinstance(params, dict):
            rpc_params.update(
                {
                    key: value
                    for key, value in params.items()
                    if key != "directory" and value is not None
                }
            )
        return rpc_params
