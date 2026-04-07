from unittest.mock import AsyncMock

import httpx
import pytest

from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.settings import make_settings

_BASE_SETTINGS = {
    "codex_timeout": 1.0,
    "a2a_log_level": "DEBUG",
}


@pytest.mark.asyncio
async def test_turn_and_review_control_methods_route_to_client(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(
            a2a_static_auth_credentials=(
                {
                    "id": "bot-turn-control",
                    "scheme": "bearer",
                    "token": "t-1",
                    "principal": "automation",
                    "capabilities": ["turn_control"],
                },
            ),
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(
            a2a_static_auth_credentials=(
                {
                    "id": "bot-turn-control",
                    "scheme": "bearer",
                    "token": "t-1",
                    "principal": "automation",
                    "capabilities": ["turn_control"],
                },
            ),
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer t-1"}
        steer_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 501,
                "method": "codex.turns.steer",
                "params": {
                    "thread_id": "thr-1",
                    "expected_turn_id": "turn-9",
                    "request": {
                        "parts": [
                            {"type": "text", "text": "Focus on the failing tests first."},
                        ]
                    },
                },
            },
        )
        review_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 502,
                "method": "codex.review.start",
                "params": {
                    "thread_id": "thr-1",
                    "delivery": "detached",
                    "target": {
                        "type": "commit",
                        "sha": "commit-demo-123",
                        "title": "Polish tui colors",
                    },
                },
            },
        )

    assert steer_response.status_code == 200
    assert steer_response.json()["result"] == {
        "ok": True,
        "thread_id": "thr-1",
        "turn_id": "turn-9",
    }
    assert dummy.last_turn_steer == {
        "thread_id": "thr-1",
        "expected_turn_id": "turn-9",
        "request": {
            "parts": [
                {"type": "text", "text": "Focus on the failing tests first."},
            ]
        },
    }

    assert review_response.status_code == 200
    assert review_response.json()["result"]["ok"] is True
    assert review_response.json()["result"]["turn_id"] == "turn-review-1"
    assert review_response.json()["result"]["review_thread_id"] == "thr-1-review"
    assert dummy.last_review_start == {
        "thread_id": "thr-1",
        "delivery": "detached",
        "target": {
            "type": "commit",
            "sha": "commit-demo-123",
            "title": "Polish tui colors",
        },
    }


@pytest.mark.asyncio
async def test_review_watch_routes_to_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(
            a2a_static_auth_credentials=(
                {
                    "id": "bot-turn-control",
                    "scheme": "bearer",
                    "token": "t-1",
                    "principal": "automation",
                    "capabilities": ["turn_control"],
                },
            ),
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(
            a2a_static_auth_credentials=(
                {
                    "id": "bot-turn-control",
                    "scheme": "bearer",
                    "token": "t-1",
                    "principal": "automation",
                    "capabilities": ["turn_control"],
                },
            ),
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )

    app.state.codex_review_runtime.start = AsyncMock(
        return_value={"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 503,
                "method": "codex.review.watch",
                "params": {
                    "thread_id": "thr-1",
                    "review_thread_id": "thr-1-review",
                    "turn_id": "turn-review-1",
                    "request": {
                        "events": [
                            "review.started",
                            "review.completed",
                        ]
                    },
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    app.state.codex_review_runtime.start.assert_awaited_once()
    kwargs = app.state.codex_review_runtime.start.await_args.kwargs
    assert kwargs == {
        "thread_id": "thr-1",
        "review_thread_id": "thr-1-review",
        "turn_id": "turn-review-1",
        "request": {"events": ["review.started", "review.completed"]},
        "context": kwargs["context"],
    }
    assert kwargs["context"] is not None


@pytest.mark.asyncio
async def test_turn_and_review_control_methods_reject_invalid_request_shapes(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer t-1"}
        steer_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 503,
                "method": "codex.turns.steer",
                "params": {
                    "thread_id": "thr-1",
                    "expected_turn_id": "turn-9",
                    "request": {"parts": []},
                },
            },
        )
        review_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 504,
                "method": "codex.review.start",
                "params": {
                    "thread_id": "thr-1",
                    "target": {"type": "baseBranch"},
                },
            },
        )
        review_watch_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 505,
                "method": "codex.review.watch",
                "params": {
                    "thread_id": "thr-1",
                    "review_thread_id": "thr-1-review",
                    "turn_id": "turn-review-1",
                    "request": {"events": ["review.delta"]},
                },
            },
        )

    assert steer_response.json()["error"]["code"] == -32602
    assert steer_response.json()["error"]["data"]["field"] == "request.parts"
    assert review_response.json()["error"]["code"] == -32602
    assert review_response.json()["error"]["data"]["field"] == "target.branch"
    assert review_watch_response.json()["error"]["code"] == -32602
    assert review_watch_response.json()["error"]["data"]["field"] == "request.events"


@pytest.mark.asyncio
async def test_turn_control_requires_turn_control_capability(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 506,
                "method": "codex.turns.steer",
                "params": {
                    "thread_id": "thr-1",
                    "expected_turn_id": "turn-9",
                    "request": {
                        "parts": [
                            {"type": "text", "text": "Focus on the failing tests first."},
                        ]
                    },
                },
            },
        )

    payload = resp.json()
    assert payload["error"]["code"] == -32007
    assert payload["error"]["data"]["type"] == "AUTHORIZATION_FORBIDDEN"
    assert payload["error"]["data"]["method"] == "codex.turns.steer"
    assert payload["error"]["data"]["capability"] == "turn_control"
    assert payload["error"]["data"]["credential_id"] == "test-bearer"
