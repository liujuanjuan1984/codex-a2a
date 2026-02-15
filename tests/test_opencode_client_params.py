import pytest

from codex_a2a_serve.codex_client import OpencodeClient, _PendingServerRequest
from tests.helpers import make_settings


@pytest.mark.asyncio
async def test_list_calls_use_expected_rpc_params() -> None:
    client = OpencodeClient(
        make_settings(
            a2a_bearer_token="t-1",
            codex_directory="/safe",
            codex_timeout=1.0,
        )
    )

    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None):
        seen.append((method, params))
        if method == "thread/list":
            return {"data": [{"id": "thr-1", "preview": "hello"}]}
        if method == "thread/read":
            return {"thread": {"turns": []}}
        return {}

    client._rpc_request = fake_rpc_request  # type: ignore[method-assign]

    sessions = await client.list_sessions(params={"directory": "/evil", "limit": 1, "roots": True})
    assert sessions == [
        {"id": "thr-1", "title": "hello", "raw": {"id": "thr-1", "preview": "hello"}}
    ]

    messages = await client.list_messages("thr-1", params={"directory": "/evil", "limit": 10})
    assert messages == []

    assert seen[0] == ("thread/list", {"limit": 1})
    assert seen[1] == ("thread/read", {"threadId": "thr-1", "includeTurns": True})


@pytest.mark.asyncio
async def test_permission_reply_maps_to_codex_decision() -> None:
    client = OpencodeClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["100"] = _PendingServerRequest(
        method="item/commandExecution/requestApproval",
        request_id=100,
        params={"threadId": "thr-1"},
    )

    sent: list[dict] = []
    events: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(event: dict) -> None:
        events.append(event)

    client._send_json_message = fake_send_json  # type: ignore[method-assign]
    client._enqueue_stream_event = fake_enqueue  # type: ignore[method-assign]

    ok = await client.permission_reply("100", reply="always")
    assert ok is True
    assert sent == [{"id": 100, "result": {"decision": "acceptForSession"}}]
    assert events[-1]["type"] == "permission.replied"
    assert "100" not in client._pending_server_requests


@pytest.mark.asyncio
async def test_question_reply_builds_answer_map() -> None:
    client = OpencodeClient(make_settings(a2a_bearer_token="t-1", codex_timeout=1.0))
    client._pending_server_requests["200"] = _PendingServerRequest(
        method="item/tool/requestUserInput",
        request_id=200,
        params={
            "threadId": "thr-2",
            "questions": [
                {"id": "q1", "question": "Q1"},
                {"id": "q2", "question": "Q2"},
            ],
        },
    )

    sent: list[dict] = []

    async def fake_send_json(payload: dict) -> None:
        sent.append(payload)

    async def fake_enqueue(_event: dict) -> None:
        return None

    client._send_json_message = fake_send_json  # type: ignore[method-assign]
    client._enqueue_stream_event = fake_enqueue  # type: ignore[method-assign]

    ok = await client.question_reply("200", answers=[["A"], ["B", "C"]])
    assert ok is True
    assert sent == [
        {
            "id": 200,
            "result": {
                "answers": {
                    "q1": {"answers": ["A"]},
                    "q2": {"answers": ["B", "C"]},
                }
            },
        }
    ]
    assert "200" not in client._pending_server_requests
