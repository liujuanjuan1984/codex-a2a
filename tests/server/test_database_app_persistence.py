from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
from a2a.types import Task, TaskState, TaskStatus

from tests.support.settings import make_settings


def _task(task_id: str, *, context_id: str = "ctx-1") -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.working),
    )


def _task_store_from_app(app):  # noqa: ANN001
    return app.state.task_store


def _executor_from_app(app):  # noqa: ANN001
    return app.state.codex_executor


@pytest.mark.asyncio
async def test_database_backend_persists_task_session_and_interrupt_state_across_app_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import codex_a2a.server.application as app_module

    class PersistentStateDummyClient:
        created_sessions = 0
        permission_reply_calls: list[dict[str, str | None]] = []

        def __init__(self, settings, *, interrupt_request_store=None) -> None:  # noqa: ANN001
            self.settings = settings
            self.directory = settings.codex_workspace_root
            self.stream_timeout = None
            self._interrupt_request_store = interrupt_request_store
            self._pending_requests: dict[str, object] = {}

        async def close(self) -> None:
            return None

        async def startup_preflight(self) -> None:
            return None

        async def restore_persisted_interrupt_requests(self) -> None:
            if self._interrupt_request_store is None:
                return
            restored = await self._interrupt_request_store.load_interrupt_requests()
            self._pending_requests = {entry.request_id: entry.binding for entry in restored}

        async def create_session(
            self,
            title: str | None = None,
            *,
            directory: str | None = None,
        ) -> str:
            del title, directory
            type(self).created_sessions += 1
            return f"ses-{type(self).created_sessions}"

        async def send_message(
            self,
            session_id: str,
            text: str,
            *,
            directory: str | None = None,
            timeout_override=None,  # noqa: ANN001
        ):
            del text, directory, timeout_override
            from codex_a2a.upstream.models import CodexMessage

            return CodexMessage(
                text="ok",
                session_id=session_id,
                message_id="m-1",
                raw={},
            )

        async def remember_interrupt_request(
            self,
            *,
            request_id: str,
            session_id: str,
            interrupt_type: str,
            task_id: str | None = None,
            context_id: str | None = None,
            identity: str | None = None,
            ttl_seconds: float | None = None,
        ) -> None:
            assert self._interrupt_request_store is not None
            from codex_a2a.upstream.interrupts import InterruptRequestBinding

            created_at = time.time()
            resolved_ttl_seconds = (
                float(ttl_seconds)
                if ttl_seconds is not None
                else float(self.settings.a2a_interrupt_request_ttl_seconds)
            )
            binding = InterruptRequestBinding(
                request_id=request_id,
                interrupt_type=interrupt_type,
                session_id=session_id,
                created_at=created_at,
                expires_at=created_at + resolved_ttl_seconds,
                identity=identity,
                task_id=task_id,
                context_id=context_id,
            )
            await self._interrupt_request_store.save_interrupt_request(
                request_id=request_id,
                interrupt_type=interrupt_type,
                session_id=session_id,
                identity=identity,
                task_id=task_id,
                context_id=context_id,
                created_at=binding.created_at,
                expires_at=binding.expires_at or binding.created_at,
                rpc_request_id=request_id,
                params={},
            )
            self._pending_requests[request_id] = binding

        async def resolve_interrupt_request(self, request_id: str):
            if self._interrupt_request_store is None:
                binding = self._pending_requests.get(request_id)
                if binding is None:
                    return "missing", None
                return "active", binding
            status, persisted = await self._interrupt_request_store.resolve_interrupt_request(
                request_id=request_id
            )
            if status != "active" or persisted is None:
                return status, None
            self._pending_requests[request_id] = persisted.binding
            return "active", persisted.binding

        async def discard_interrupt_request(self, request_id: str) -> None:
            self._pending_requests.pop(request_id, None)

        async def permission_reply(
            self,
            request_id: str,
            *,
            reply: str,
            message: str | None = None,
            directory: str | None = None,
        ) -> bool:
            type(self).permission_reply_calls.append(
                {
                    "request_id": request_id,
                    "reply": reply,
                    "message": message,
                    "directory": directory,
                }
            )
            await self.discard_interrupt_request(request_id)
            if self._interrupt_request_store is not None:
                await self._interrupt_request_store.delete_interrupt_request(request_id=request_id)
            return True

    PersistentStateDummyClient.created_sessions = 0
    PersistentStateDummyClient.permission_reply_calls = []
    monkeypatch.setattr(app_module, "CodexClient", PersistentStateDummyClient)

    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'app-state.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    request_identity = (
        f"bearer:{hashlib.sha256(settings.a2a_bearer_token.encode()).hexdigest()[:12]}"
    )
    database_path = (tmp_path / "app-state.db").resolve()

    app1 = app_module.create_app(settings)
    async with app1.router.lifespan_context(app1):
        task_store = _task_store_from_app(app1)
        executor = _executor_from_app(app1)
        codex_client = app1.state.codex_client

        await task_store.save(_task("task-1"))
        session_id, pending = await executor._session_runtime.get_or_create_session(
            identity=request_identity,
            context_id="ctx-1",
            title="hello",
            preferred_session_id=None,
            create_session=lambda: codex_client.create_session(title="hello"),
        )
        assert pending is False
        assert session_id == "ses-1"

        await codex_client.remember_interrupt_request(
            request_id="perm-1",
            session_id=session_id,
            interrupt_type="permission",
            task_id="task-1",
            context_id="ctx-1",
        )

    assert _sqlite_schema_version(database_path, "runtime_state") == 1

    app2 = app_module.create_app(settings)
    async with app2.router.lifespan_context(app2):
        task_store = _task_store_from_app(app2)
        executor = _executor_from_app(app2)

        restored_task = await task_store.get("task-1")
        assert restored_task is not None
        assert restored_task.id == "task-1"

        restored_session_id, pending = await executor._session_runtime.get_or_create_session(
            identity=request_identity,
            context_id="ctx-1",
            title="hello again",
            preferred_session_id=None,
            create_session=lambda: app2.state.codex_client.create_session(title="hello again"),
        )
        assert pending is False
        assert restored_session_id == "ses-1"
        assert PersistentStateDummyClient.created_sessions == 1
        (
            interrupt_status,
            interrupt_binding,
        ) = await app2.state.codex_client.resolve_interrupt_request("perm-1")
        assert interrupt_status == "active"
        assert interrupt_binding is not None
        assert interrupt_binding.task_id == "task-1"
        assert interrupt_binding.context_id == "ctx-1"
        assert interrupt_binding.identity is None

        transport = httpx.ASGITransport(app=app2)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "a2a.interrupt.permission.reply",
                    "params": {
                        "request_id": "perm-1",
                        "reply": "once",
                    },
                },
            )

        payload = response.json()
        assert payload.get("error") is None
        assert payload["result"]["ok"] is True
        assert payload["result"]["request_id"] == "perm-1"
        assert PersistentStateDummyClient.permission_reply_calls == [
            {
                "request_id": "perm-1",
                "reply": "once",
                "message": None,
                "directory": None,
            }
        ]


def _sqlite_schema_version(database_path: Path, scope: str) -> int | None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            "SELECT version FROM a2a_schema_version WHERE scope = ?",
            (scope,),
        ).fetchone()
        return None if row is None else int(row[0])
    finally:
        connection.close()
