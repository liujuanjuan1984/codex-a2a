from __future__ import annotations

import asyncio
import sqlite3

import pytest

from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.upstream.client import CodexClient
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_interrupt_requests_restore_after_client_rebuild(tmp_path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        codex_timeout=1.0,
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        client_1 = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        client_1.bind_interrupt_context(
            session_id="thr-1",
            identity="user-1",
            credential_id="cred-1",
            task_id="task-1",
            context_id="ctx-1",
        )
        await client_1._handle_server_request(
            {
                "id": 100,
                "method": "item/tool/requestUserInput",
                "params": {
                    "threadId": "thr-1",
                    "questions": [{"id": "q1", "question": "Q1"}],
                },
            }
        )

        client_2 = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        await client_2.restore_persisted_interrupt_requests()
        status, binding = await client_2.resolve_interrupt_request("100")
        await client_2.discard_interrupt_request("100")
        await asyncio.sleep(0)

        client_3 = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        await client_3.restore_persisted_interrupt_requests()
        missing_status, missing_binding = await client_3.resolve_interrupt_request("100")
    finally:
        await runtime_state.shutdown()

    assert status == "active"
    assert binding is not None
    assert binding.session_id == "thr-1"
    assert binding.identity == "user-1"
    assert binding.credential_id == "cred-1"
    assert binding.task_id == "task-1"
    assert binding.context_id == "ctx-1"
    assert missing_status == "missing"
    assert missing_binding is None


@pytest.mark.asyncio
async def test_expired_interrupt_requests_are_not_restored(tmp_path, monkeypatch) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        codex_timeout=1.0,
        a2a_interrupt_request_ttl_seconds=5,
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 10.0)
        client_1 = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        await client_1._handle_server_request(
            {
                "id": 200,
                "method": "item/commandExecution/requestApproval",
                "params": {"threadId": "thr-2"},
            }
        )

        monkeypatch.setattr("codex_a2a.server.runtime_state.time.time", lambda: 16.0)
        monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 16.0)
        monkeypatch.setattr("codex_a2a.upstream.interrupts.time.time", lambda: 16.0)
        client_2 = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        await client_2.restore_persisted_interrupt_requests()
        status, binding = await client_2.resolve_interrupt_request("200")
        repeated_status, repeated_binding = await client_2.resolve_interrupt_request("200")

        monkeypatch.setattr("codex_a2a.server.runtime_state.time.time", lambda: 617.0)
        monkeypatch.setattr("codex_a2a.upstream.client.time.time", lambda: 617.0)
        monkeypatch.setattr("codex_a2a.upstream.interrupts.time.time", lambda: 617.0)
        missing_status, missing_binding = await client_2.resolve_interrupt_request("200")
    finally:
        await runtime_state.shutdown()

    assert status == "expired"
    assert binding is None
    assert repeated_status == "expired"
    assert repeated_binding is None
    assert missing_status == "missing"
    assert binding is None
    assert missing_binding is None


@pytest.mark.asyncio
async def test_legacy_interrupt_request_rows_restore_after_schema_upgrade(tmp_path) -> None:
    database_path = (tmp_path / "legacy-runtime.db").resolve()
    _create_legacy_interrupt_request_row(database_path)
    settings = make_settings(
        a2a_bearer_token="test-token",
        codex_timeout=1.0,
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )

    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        client = CodexClient(settings, interrupt_request_store=runtime_state.state_store)
        await client.restore_persisted_interrupt_requests()
        status, binding = await client.resolve_interrupt_request("legacy-1")
    finally:
        await runtime_state.shutdown()

    assert status == "active"
    assert binding is not None
    assert binding.session_id == "thr-legacy"
    assert binding.identity is None
    assert binding.credential_id is None
    assert binding.task_id is None
    assert binding.context_id is None


def _create_legacy_interrupt_request_row(database_path) -> None:  # noqa: ANN001
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE a2a_pending_interrupt_requests (
                request_id TEXT PRIMARY KEY,
                interrupt_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at FLOAT NOT NULL,
                rpc_request_id JSON NOT NULL,
                params JSON NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO a2a_pending_interrupt_requests (
                request_id,
                interrupt_type,
                session_id,
                created_at,
                rpc_request_id,
                params
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("legacy-1", "permission", "thr-legacy", 4102444800.0, '"legacy-1"', "{}"),
        )
        connection.commit()
    finally:
        connection.close()
