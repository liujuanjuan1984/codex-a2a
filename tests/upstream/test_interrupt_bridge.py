from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codex_a2a.upstream.interrupt_bridge import CodexInterruptBridge
from codex_a2a.upstream.interrupts import InterruptRequestBinding, _PendingInterruptRequest


async def _append_event(events: list[dict[str, object]], event: dict[str, object]) -> None:
    events.append(event)


@pytest.mark.asyncio
async def test_handle_server_request_registers_permission_interrupt_with_bound_context() -> None:
    events: list[dict[str, object]] = []
    send_json_message = AsyncMock()
    store = SimpleNamespace(
        save_interrupt_request=AsyncMock(),
        expire_interrupt_request=AsyncMock(),
        delete_interrupt_request=AsyncMock(),
        resolve_interrupt_request=AsyncMock(),
        load_interrupt_requests=AsyncMock(return_value=[]),
    )
    bridge = CodexInterruptBridge(
        now=lambda: 100.0,
        interrupt_request_ttl_seconds=30,
        interrupt_request_tombstone_ttl_seconds=60,
        interrupt_request_store=store,
    )
    bridge.bind_interrupt_context(
        session_id="thr-1",
        identity=" user-1 ",
        credential_id=" cred-1 ",
        task_id="task-1",
        context_id="ctx-1",
    )

    await bridge.handle_server_request(
        {
            "id": 100,
            "method": "item/fileChange/requestApproval",
            "params": {
                "threadId": "thr-1",
                "reason": "Need approval",
                "parsedCmd": [{"path": "/tmp/a"}, {"path": "/tmp/a"}],
            },
        },
        send_json_message=send_json_message,
        enqueue_stream_event=lambda event: _append_event(events, event),
    )

    pending = bridge.pending_server_requests["100"]
    assert pending.binding == InterruptRequestBinding(
        request_id="100",
        interrupt_type="permission",
        session_id="thr-1",
        created_at=100.0,
        expires_at=130.0,
        identity="user-1",
        credential_id="cred-1",
        task_id="task-1",
        context_id="ctx-1",
    )
    assert events == [
        {
            "type": "permission.asked",
            "properties": {
                "id": "100",
                "sessionID": "thr-1",
                "metadata": {
                    "method": "item/fileChange/requestApproval",
                    "raw": {
                        "threadId": "thr-1",
                        "reason": "Need approval",
                        "parsedCmd": [{"path": "/tmp/a"}, {"path": "/tmp/a"}],
                    },
                },
                "display_message": "Need approval",
                "permission": "file_change",
                "patterns": ["/tmp/a"],
            },
        }
    ]
    send_json_message.assert_not_called()
    store.save_interrupt_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_server_request_returns_error_for_unsupported_method() -> None:
    sent: list[dict[str, object]] = []
    bridge = CodexInterruptBridge(
        now=lambda: 10.0,
        interrupt_request_ttl_seconds=30,
        interrupt_request_tombstone_ttl_seconds=60,
    )

    await bridge.handle_server_request(
        {"id": "rpc-1", "method": "custom/unknown", "params": {}},
        send_json_message=lambda message: _append_event(sent, message),
        enqueue_stream_event=AsyncMock(),
    )

    assert sent == [
        {
            "id": "rpc-1",
            "error": {
                "code": -32601,
                "message": "Unsupported server request method: custom/unknown",
            },
        }
    ]


@pytest.mark.asyncio
async def test_list_interrupt_requests_filters_visibility_and_expires_stale_entries() -> None:
    store = SimpleNamespace(
        expire_interrupt_request=AsyncMock(),
        delete_interrupt_request=AsyncMock(),
        resolve_interrupt_request=AsyncMock(),
        save_interrupt_request=AsyncMock(),
        load_interrupt_requests=AsyncMock(return_value=[]),
    )
    bridge = CodexInterruptBridge(
        now=lambda: 50.0,
        interrupt_request_ttl_seconds=10,
        interrupt_request_tombstone_ttl_seconds=60,
        interrupt_request_store=store,
    )
    bridge.pending_server_requests["active-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="active-1",
            interrupt_type="question",
            session_id="thr-1",
            created_at=45.0,
            expires_at=70.0,
            identity="user-1",
            credential_id="cred-1",
            task_id="task-1",
            context_id="ctx-1",
        ),
        rpc_request_id="active-1",
        params={"questions": [{"id": "q1", "question": "Q1"}]},
    )
    bridge.pending_server_requests["expired-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="expired-1",
            interrupt_type="permission",
            session_id="thr-2",
            created_at=20.0,
            expires_at=30.0,
            identity="user-1",
            credential_id="cred-1",
        ),
        rpc_request_id="expired-1",
        params={},
    )
    bridge.pending_server_requests["foreign-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="foreign-1",
            interrupt_type="question",
            session_id="thr-3",
            created_at=45.0,
            expires_at=70.0,
            identity="user-2",
            credential_id="cred-1",
        ),
        rpc_request_id="foreign-1",
        params={"questions": []},
    )

    items = await bridge.list_interrupt_requests(
        identity="user-1",
        credential_id="cred-1",
        interrupt_type="question",
    )

    assert items == [
        {
            "request_id": "active-1",
            "interrupt_type": "question",
            "session_id": "thr-1",
            "task_id": "task-1",
            "context_id": "ctx-1",
            "created_at": 45.0,
            "expires_at": 70.0,
            "properties": {
                "id": "active-1",
                "sessionID": "thr-1",
                "questions": [{"id": "q1", "question": "Q1"}],
                "metadata": {
                    "method": "item/tool/requestUserInput",
                    "raw": {"questions": [{"id": "q1", "question": "Q1"}]},
                },
            },
        }
    ]
    assert "expired-1" not in bridge.pending_server_requests
    assert "expired-1" in bridge.expired_server_requests
    store.expire_interrupt_request.assert_awaited_once_with(request_id="expired-1")


@pytest.mark.asyncio
async def test_question_reply_maps_answers_by_question_id_and_discards_request() -> None:
    sent: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    bridge = CodexInterruptBridge(
        now=lambda: 10.0,
        interrupt_request_ttl_seconds=30,
        interrupt_request_tombstone_ttl_seconds=60,
    )
    bridge.pending_server_requests["req-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="req-1",
            interrupt_type="question",
            session_id="thr-1",
            created_at=0.0,
            expires_at=100.0,
        ),
        rpc_request_id="rpc-1",
        params={"questions": [{"id": "q1"}, {"id": "q2"}, {"skip": True}]},
    )

    ok = await bridge.question_reply(
        "req-1",
        answers=[["A"], ["B", "C"]],
        send_json_message=lambda message: _append_event(sent, message),
        enqueue_stream_event=lambda event: _append_event(events, event),
    )

    assert ok is True
    assert sent == [
        {
            "id": "rpc-1",
            "result": {
                "answers": {
                    "q1": {"answers": ["A"]},
                    "q2": {"answers": ["B", "C"]},
                }
            },
        }
    ]
    assert events == [
        {
            "type": "question.replied",
            "properties": {"id": "req-1", "requestID": "req-1", "sessionID": "thr-1"},
        }
    ]
    assert "req-1" not in bridge.pending_server_requests


@pytest.mark.asyncio
async def test_question_reject_and_elicitation_reply_emit_terminal_events() -> None:
    bridge = CodexInterruptBridge(
        now=lambda: 10.0,
        interrupt_request_ttl_seconds=30,
        interrupt_request_tombstone_ttl_seconds=60,
    )
    bridge.pending_server_requests["question-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="question-1",
            interrupt_type="question",
            session_id="thr-q",
            created_at=0.0,
            expires_at=100.0,
        ),
        rpc_request_id="rpc-q",
        params={"questions": []},
    )
    bridge.pending_server_requests["elicitation-1"] = _PendingInterruptRequest(
        binding=InterruptRequestBinding(
            request_id="elicitation-1",
            interrupt_type="elicitation",
            session_id="thr-e",
            created_at=0.0,
            expires_at=100.0,
        ),
        rpc_request_id="rpc-e",
        params={},
    )
    sent: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    await bridge.question_reject(
        "question-1",
        send_json_message=lambda message: _append_event(sent, message),
        enqueue_stream_event=lambda event: _append_event(events, event),
    )
    await bridge.elicitation_reply(
        "elicitation-1",
        action="decline",
        content=None,
        send_json_message=lambda message: _append_event(sent, message),
        enqueue_stream_event=lambda event: _append_event(events, event),
    )

    assert sent == [
        {"id": "rpc-q", "result": {"answers": {}}},
        {"id": "rpc-e", "result": {"action": "decline", "content": None}},
    ]
    assert events == [
        {
            "type": "question.rejected",
            "properties": {"id": "question-1", "requestID": "question-1", "sessionID": "thr-q"},
        },
        {
            "type": "elicitation.rejected",
            "properties": {
                "id": "elicitation-1",
                "requestID": "elicitation-1",
                "sessionID": "thr-e",
            },
        },
    ]
