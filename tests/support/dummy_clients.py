from __future__ import annotations

from typing import Any

from codex_a2a.config import Settings
from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.upstream.client import CodexMessage
from codex_a2a.upstream.interrupts import (
    InterruptRequestBinding,
    build_codex_elicitation_interrupt_properties,
    build_codex_permission_interrupt_properties,
    build_codex_permissions_interrupt_properties,
    build_codex_question_interrupt_properties,
)
from tests.support.settings import make_settings


class DummyChatCodexClient:
    def __init__(self, settings: Settings | None = None, **kwargs: Any) -> None:
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

    async def restore_persisted_interrupt_requests(self) -> None:
        return None

    async def create_session(
        self,
        title: str | None = None,
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> str:
        del title, directory, execution_options
        self.created_sessions += 1
        return f"ses-created-{self.created_sessions}"

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        input_items: list[dict[str, Any]] | None = None,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
        timeout_override=None,  # noqa: ANN001
    ) -> CodexMessage:
        del directory, timeout_override
        self.sent_session_ids.append(session_id)
        self.sent_inputs.append(
            {
                "text": text,
                "input_items": input_items,
                "execution_options": execution_options,
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
    def __init__(self, _settings: Settings, **kwargs: Any) -> None:
        self.directory = "/workspace"
        self.settings = _settings
        self._sessions_payload: Any = [{"id": "s-1", "title": "Session s-1"}]
        self._messages_payload: Any = [
            {
                "info": {"id": "m-1", "role": "assistant"},
                "parts": [{"type": "text", "text": "SECRET_HISTORY"}],
            }
        ]
        self._skills_payload: Any = {
            "data": [
                {
                    "cwd": "/workspace/project",
                    "skills": [
                        {
                            "name": "skill-creator",
                            "path": "/workspace/project/.codex/skills/skill-creator/SKILL.md",
                            "description": "Create or update a Codex skill",
                            "enabled": True,
                            "scope": "repo",
                            "interface": {"displayName": "Skill Creator"},
                        }
                    ],
                    "errors": [],
                }
            ]
        }
        self._apps_payload: Any = {
            "data": [
                {
                    "id": "demo-app",
                    "name": "Demo App",
                    "description": "Example connector",
                    "installUrl": "https://example.com/apps/demo-app",
                    "isAccessible": True,
                    "isEnabled": True,
                }
            ],
            "nextCursor": None,
        }
        self._plugins_payload: Any = {
            "marketplaces": [
                {
                    "name": "test",
                    "path": "/workspace/project/.codex/plugins/marketplace.json",
                    "plugins": [
                        {
                            "name": "sample",
                            "description": "Sample plugin",
                            "enabled": True,
                            "interface": {"category": "utility"},
                        }
                    ],
                }
            ],
            "featuredPluginIds": ["sample@test"],
            "marketplaceLoadErrors": [],
            "remoteSyncError": None,
        }
        self._plugin_read_payload: Any = {
            "plugin": {
                "name": "sample",
                "marketplaceName": "test",
                "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
                "summary": ["Sample plugin"],
                "skills": [],
                "apps": [],
                "mcpServers": [],
                "interface": {"category": "utility"},
            }
        }
        self.last_sessions_params = None
        self.last_messages_params = None
        self.last_skills_params = None
        self.last_apps_params = None
        self.last_plugins_params = None
        self.last_plugin_read_params = None
        self.last_thread_fork: dict[str, Any] | None = None
        self.last_thread_archive: dict[str, Any] | None = None
        self.last_thread_unarchive: dict[str, Any] | None = None
        self.last_thread_metadata_update: dict[str, Any] | None = None
        self.last_turn_steer: dict[str, Any] | None = None
        self.last_review_start: dict[str, Any] | None = None
        self.last_prompt_async: dict[str, Any] | None = None
        self.last_command: dict[str, Any] | None = None
        self.last_shell: dict[str, Any] | None = None
        self.exec_write_calls: list[dict[str, Any]] = []
        self.exec_resize_calls: list[dict[str, Any]] = []
        self.exec_terminate_calls: list[dict[str, Any]] = []
        self.permission_reply_calls: list[dict[str, Any]] = []
        self.question_reply_calls: list[dict[str, Any]] = []
        self.question_reject_calls: list[dict[str, Any]] = []
        self.permissions_reply_calls: list[dict[str, Any]] = []
        self.elicitation_reply_calls: list[dict[str, Any]] = []
        self._interrupt_requests: dict[str, InterruptRequestBinding] = {}
        self._interrupt_request_params: dict[str, dict[str, Any]] = {}
        self._expired_interrupt_requests: set[str] = set()

    async def close(self) -> None:
        return None

    async def startup_preflight(self) -> None:
        return None

    async def restore_persisted_interrupt_requests(self) -> None:
        return None

    async def list_sessions(self, *, params=None):
        self.last_sessions_params = params
        return self._sessions_payload

    async def list_messages(self, session_id: str, *, params=None):
        assert session_id
        self.last_messages_params = params
        return self._messages_payload

    async def list_skills(self, *, params=None):
        self.last_skills_params = params
        return self._skills_payload

    async def list_apps(self, *, params=None):
        self.last_apps_params = params
        return self._apps_payload

    async def list_plugins(self, *, params=None):
        self.last_plugins_params = params
        return self._plugins_payload

    async def read_plugin(self, *, params=None):
        self.last_plugin_read_params = params
        return self._plugin_read_payload

    async def thread_fork(self, thread_id: str, *, params=None):
        self.last_thread_fork = {"thread_id": thread_id, "params": params}
        return {
            "id": f"{thread_id}-fork",
            "title": f"Fork of {thread_id}",
            "status": {"type": "idle"},
            "raw": {
                "id": f"{thread_id}-fork",
                "preview": f"Fork of {thread_id}",
                "status": {"type": "idle"},
            },
        }

    async def thread_archive(self, thread_id: str) -> None:
        self.last_thread_archive = {"thread_id": thread_id}

    async def thread_unarchive(self, thread_id: str):
        self.last_thread_unarchive = {"thread_id": thread_id}
        return {
            "id": thread_id,
            "title": f"Restored {thread_id}",
            "status": {"type": "notLoaded"},
            "raw": {
                "id": thread_id,
                "preview": f"Restored {thread_id}",
                "status": {"type": "notLoaded"},
            },
        }

    async def thread_metadata_update(self, thread_id: str, *, params=None):
        self.last_thread_metadata_update = {"thread_id": thread_id, "params": params}
        branch = None
        if isinstance(params, dict):
            git_info = params.get("gitInfo")
            if isinstance(git_info, dict):
                branch = git_info.get("branch")
        return {
            "id": thread_id,
            "title": f"Thread {thread_id}",
            "status": {"type": "notLoaded"},
            "raw": {
                "id": thread_id,
                "preview": f"Thread {thread_id}",
                "status": {"type": "notLoaded"},
                "gitInfo": {"branch": branch},
            },
        }

    async def turn_steer(
        self,
        thread_id: str,
        *,
        expected_turn_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.last_turn_steer = {
            "thread_id": thread_id,
            "expected_turn_id": expected_turn_id,
            "request": request,
        }
        return {"ok": True, "thread_id": thread_id, "turn_id": expected_turn_id}

    async def review_start(
        self,
        thread_id: str,
        *,
        target: dict[str, Any],
        delivery: str | None = None,
    ) -> dict[str, Any]:
        self.last_review_start = {
            "thread_id": thread_id,
            "target": target,
            "delivery": delivery,
        }
        review_thread_id = thread_id if delivery != "detached" else f"{thread_id}-review"
        return {
            "ok": True,
            "turn_id": "turn-review-1",
            "review_thread_id": review_thread_id,
        }

    async def session_prompt_async(
        self,
        session_id: str,
        *,
        request=None,
        directory=None,
        execution_options: RequestExecutionOptions | None = None,
    ):
        self.last_prompt_async = {
            "session_id": session_id,
            "request": request,
            "directory": directory,
            "execution_options": execution_options,
        }
        return {"ok": True, "session_id": session_id, "turn_id": "turn-1"}

    async def session_command(
        self,
        session_id: str,
        *,
        request=None,
        directory=None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> CodexMessage:
        self.last_command = {
            "session_id": session_id,
            "request": request,
            "directory": directory,
            "execution_options": execution_options,
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
        del directory
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
        self._interrupt_request_params.pop(request_id, None)
        self._expired_interrupt_requests.discard(request_id)

    def prime_interrupt_request(
        self,
        request_id: str,
        *,
        interrupt_type: str,
        session_id: str = "ses-1",
        created_at: float = 0.0,
        identity: str | None = None,
        credential_id: str | None = None,
        task_id: str | None = None,
        context_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self._interrupt_requests[request_id] = InterruptRequestBinding(
            request_id=request_id,
            interrupt_type=interrupt_type,
            session_id=session_id,
            created_at=created_at,
            identity=identity,
            credential_id=credential_id,
            task_id=task_id,
            context_id=context_id,
        )
        self._interrupt_request_params[request_id] = dict(params or {})
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

    async def list_interrupt_requests(
        self,
        *,
        identity: str | None,
        credential_id: str | None,
        interrupt_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if identity is None and credential_id is None:
            return []

        builder_by_type = {
            "permission": build_codex_permission_interrupt_properties,
            "question": build_codex_question_interrupt_properties,
            "permissions": build_codex_permissions_interrupt_properties,
            "elicitation": build_codex_elicitation_interrupt_properties,
        }
        default_method = {
            "permission": "item/commandExecution/requestApproval",
            "question": "item/tool/requestUserInput",
            "permissions": "item/permissions/requestApproval",
            "elicitation": "mcpServer/elicitation/request",
        }

        items: list[dict[str, Any]] = []
        for request_id, binding in self._interrupt_requests.items():
            if request_id in self._expired_interrupt_requests:
                continue
            if interrupt_type is not None and binding.interrupt_type != interrupt_type:
                continue
            if binding.identity is not None and binding.identity != identity:
                continue
            if binding.credential_id is not None and binding.credential_id != credential_id:
                continue
            if binding.identity is None and binding.credential_id is None:
                continue
            builder = builder_by_type.get(binding.interrupt_type)
            if builder is None:
                properties = {"id": request_id, "sessionID": binding.session_id}
            else:
                properties = builder(
                    request_key=request_id,
                    session_id=binding.session_id,
                    method=default_method[binding.interrupt_type],
                    params=dict(self._interrupt_request_params.get(request_id, {})),
                )
            items.append(
                {
                    "request_id": request_id,
                    "interrupt_type": binding.interrupt_type,
                    "session_id": binding.session_id,
                    "task_id": binding.task_id,
                    "context_id": binding.context_id,
                    "created_at": binding.created_at,
                    "expires_at": binding.expires_at,
                    "properties": properties,
                }
            )
        items.sort(key=lambda item: (item["created_at"], item["request_id"]))
        return items
