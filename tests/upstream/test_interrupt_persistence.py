from __future__ import annotations

import asyncio

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
