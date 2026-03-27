from __future__ import annotations

from typing import Any

from codex_a2a.config import Settings
from codex_a2a.upstream.client import CodexMessage
from codex_a2a.upstream.interrupts import InterruptRequestBinding
from tests.support.settings import make_settings


class DummyChatCodexClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.created_sessions = 0
        self.sent_session_ids: list[str] = []
        self.sent_inputs: list[dict[str, Any]] = []
        self.stream_timeout = None
        self.directory = None
        self.settings = settings or make_settings(
            a2a_bearer_token="test",
        )

    async def close(self) -> None:
        return None

    async def startup_preflight(self) -> None:
        return None

    async def create_session(
        self,
        title: str | None = None,
        *,
        directory: str | None = None,
    ) -> str:
        del title, directory
        self.created_sessions += 1
        return f"ses-created-{self.created_sessions}"

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        input_items: list[dict[str, Any]] | None = None,
        directory: str | None = None,
        timeout_override=None,  # noqa: ANN001
    ) -> CodexMessage:
        del directory, timeout_override
        self.sent_session_ids.append(session_id)
        self.sent_inputs.append(
            {
                "text": text,
                "input_items": input_items,
            }
        )
        return CodexMessage(
            text=f"echo:{text}",
            session_id=session_id,
            message_id="m-1",
            raw={},
        )

    async def stream_events(self, stop_event=None, *, directory: str | None = None):  # noqa: ANN001
        del stop_event, directory
        for _ in ():
            yield {}

    async def discard_interrupt_request(self, request_id: str) -> None:
        del request_id


class DummySessionQueryCodexClient:
    def __init__(self, _settings: Settings) -> None:
        self.directory = "/workspace"
        self.settings = _settings
        self._sessions_payload: Any = [{"id": "s-1", "title": "Session s-1"}]
        self._messages_payload: Any = [
            {
                "info": {"id": "m-1", "role": "assistant"},
                "parts": [{"type": "text", "text": "SECRET_HISTORY"}],
            }
        ]
        self.last_sessions_params = None
        self.last_messages_params = None
        self.last_prompt_async: dict[str, Any] | None = None
        self.last_command: dict[str, Any] | None = None
        self.last_shell: dict[str, Any] | None = None
        self.last_exec_start: dict[str, Any] | None = None
        self.exec_write_calls: list[dict[str, Any]] = []
        self.exec_resize_calls: list[dict[str, Any]] = []
        self.exec_terminate_calls: list[dict[str, Any]] = []
        self.permission_reply_calls: list[dict[str, Any]] = []
        self.question_reply_calls: list[dict[str, Any]] = []
        self.question_reject_calls: list[dict[str, Any]] = []
        self.permissions_reply_calls: list[dict[str, Any]] = []
        self.elicitation_reply_calls: list[dict[str, Any]] = []
        self._interrupt_requests: dict[str, InterruptRequestBinding] = {}
        self._expired_interrupt_requests: set[str] = set()

    async def close(self) -> None:
        return None

    async def list_sessions(self, *, params=None):
        self.last_sessions_params = params
        return self._sessions_payload

    async def list_messages(self, session_id: str, *, params=None):
        assert session_id
        self.last_messages_params = params
        return self._messages_payload

    async def session_prompt_async(self, session_id: str, *, request=None, directory=None):
        self.last_prompt_async = {
            "session_id": session_id,
            "request": request,
            "directory": directory,
        }
        return {"ok": True, "session_id": session_id, "turn_id": "turn-1"}

    async def session_command(
        self, session_id: str, *, request=None, directory=None
    ) -> CodexMessage:
        self.last_command = {
            "session_id": session_id,
            "request": request,
            "directory": directory,
        }
        return CodexMessage(
            text=f"command:{request['command']} {request.get('arguments', '')}".strip(),
            session_id=session_id,
            message_id=request.get("messageID") or "cmd-1",
            raw={"request": request},
        )

    async def session_shell(self, session_id: str, *, request=None, directory=None):
        self.last_shell = {
            "session_id": session_id,
            "request": request,
            "directory": directory,
        }
        return {
            "info": {"id": "shell-1", "role": "assistant"},
            "parts": [{"type": "text", "text": f"stdout\n$ {request['command']}"}],
            "raw": {"request": request},
        }

    async def exec_start(
        self,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        timeout_override=None,  # noqa: ANN001
    ) -> dict[str, Any]:
        del timeout_override
        self.last_exec_start = {
            "request": request,
            "directory": directory,
        }
        process_id = str(request.get("processId") or "exec-1")
        return {"stdout": "hello\n", "stderr": "", "exitCode": 0, "processId": process_id}

    async def exec_write(
        self,
        *,
        process_id: str,
        delta_base64: str | None = None,
        close_stdin: bool | None = None,
    ) -> None:
        self.exec_write_calls.append(
            {
                "process_id": process_id,
                "delta_base64": delta_base64,
                "close_stdin": close_stdin,
            }
        )

    async def exec_resize(self, *, process_id: str, rows: int, cols: int) -> None:
        self.exec_resize_calls.append(
            {
                "process_id": process_id,
                "rows": rows,
                "cols": cols,
            }
        )

    async def exec_terminate(self, *, process_id: str) -> None:
        self.exec_terminate_calls.append({"process_id": process_id})

    async def permission_reply(
        self,
        request_id: str,
        *,
        reply: str,
        message: str | None = None,
        directory: str | None = None,
    ) -> bool:
        self.permission_reply_calls.append(
            {
                "request_id": request_id,
                "reply": reply,
                "message": message,
                "directory": directory,
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def question_reply(
        self,
        request_id: str,
        *,
        answers: list[list[str]],
        directory: str | None = None,
    ) -> bool:
        self.question_reply_calls.append(
            {
                "request_id": request_id,
                "answers": answers,
                "directory": directory,
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def question_reject(
        self,
        request_id: str,
        *,
        directory: str | None = None,
    ) -> bool:
        self.question_reject_calls.append(
            {
                "request_id": request_id,
                "directory": directory,
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def permissions_reply(
        self,
        request_id: str,
        *,
        permissions: dict[str, Any],
        scope: str | None = None,
        directory: str | None = None,
    ) -> bool:
        self.permissions_reply_calls.append(
            {
                "request_id": request_id,
                "permissions": permissions,
                "scope": scope,
                "directory": directory,
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def elicitation_reply(
        self,
        request_id: str,
        *,
        action: str,
        content: Any = None,
        directory: str | None = None,
    ) -> bool:
        self.elicitation_reply_calls.append(
            {
                "request_id": request_id,
                "action": action,
                "content": content,
                "directory": directory,
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def discard_interrupt_request(self, request_id: str) -> None:
        self._interrupt_requests.pop(request_id, None)
        self._expired_interrupt_requests.discard(request_id)

    def prime_interrupt_request(
        self,
        request_id: str,
        *,
        interrupt_type: str,
        session_id: str = "ses-1",
        created_at: float = 0.0,
        identity: str | None = None,
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> None:
        self._interrupt_requests[request_id] = InterruptRequestBinding(
            request_id=request_id,
            interrupt_type=interrupt_type,
            session_id=session_id,
            created_at=created_at,
            identity=identity,
            task_id=task_id,
            context_id=context_id,
        )
        self._expired_interrupt_requests.discard(request_id)

    async def resolve_interrupt_request(
        self,
        request_id: str,
    ) -> tuple[str, InterruptRequestBinding | None]:
        if request_id in self._expired_interrupt_requests:
            return "expired", None
        binding = self._interrupt_requests.get(request_id)
        if binding is None:
            return "missing", None
        if binding.created_at == 0.0:
            return "active", binding
        self._interrupt_requests.pop(request_id, None)
        self._expired_interrupt_requests.add(request_id)
        return "expired", None
