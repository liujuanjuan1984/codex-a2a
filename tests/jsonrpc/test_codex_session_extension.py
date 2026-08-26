from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from a2a.server.jsonrpc_models import InternalError

from codex_a2a.contracts.extensions import (
    DISCOVERY_EXTENSION_URI,
    EXTENSION_JSONRPC_PATH,
    INTERRUPT_RECOVERY_EXTENSION_URI,
    SESSION_QUERY_EXTENSION_URI,
)
from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.jsonrpc_errors import error_context, error_reason
from tests.support.settings import make_settings

_BASE_SETTINGS = {
    "codex_timeout": 1.0,
    "a2a_log_level": "DEBUG",
}
_EXTENSION_HEADERS = {
    "Authorization": "Bearer t-1",
    "A2A-Extensions": SESSION_QUERY_EXTENSION_URI,
}


def _build_app(monkeypatch: pytest.MonkeyPatch, dummy: DummyCodexClient):
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    return app_module.create_app(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )


@pytest.mark.asyncio
async def test_session_list_routes_to_query_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={
                **_EXTENSION_HEADERS,
                "A2A-Extensions": (
                    f"{DISCOVERY_EXTENSION_URI},{SESSION_QUERY_EXTENSION_URI},"
                    "https://example.test/unknown"
                ),
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "codex.sessions.list",
                "params": {"limit": 5},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["items"][0]["context_id"] == "s-1"
    assert dummy.last_sessions_params == {"limit": 5}
    assert response.headers["A2A-Extensions"] == SESSION_QUERY_EXTENSION_URI


@pytest.mark.asyncio
async def test_session_messages_routes_to_query_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "codex.sessions.messages.list",
                "params": {"session_id": "s-1", "limit": 5},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["items"][0]["message_id"] == "m-1"
    assert dummy.last_messages_params == {"limit": 5}


@pytest.mark.asyncio
async def test_removed_session_control_methods_return_method_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "codex.sessions.command",
                "params": {
                    "session_id": "s-1",
                    "request": {"command": "plan", "arguments": "show current work"},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32601
    assert payload["error"]["data"]["method"] == "codex.sessions.command"
    assert "codex.sessions.command" not in payload["error"]["data"]["supported_methods"]
    assert "A2A-Extensions" not in response.headers


@pytest.mark.asyncio
async def test_session_query_requires_matching_extension_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    dummy.list_sessions = AsyncMock(side_effect=AssertionError("should not be called"))  # type: ignore[method-assign]
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={
                "Authorization": "Bearer t-1",
                "A2A-Extensions": f"https://example.test/unknown,{DISCOVERY_EXTENSION_URI}",
            },
            json={
                "jsonrpc": "2.0",
                "id": 31,
                "method": "codex.sessions.list",
                "params": {"limit": 5},
            },
        )

    payload = response.json()
    assert payload["error"]["code"] == -32004
    assert error_reason(payload) == "EXTENSION_NEGOTIATION_REQUIRED"
    context = error_context(payload)
    assert context == {
        "@type": "type.googleapis.com/codex_a2a.ErrorContext",
        "method": "codex.sessions.list",
        "required_extensions": [SESSION_QUERY_EXTENSION_URI],
        "requested_extensions": [
            "https://example.test/unknown",
            DISCOVERY_EXTENSION_URI,
        ],
        "header": "A2A-Extensions",
    }
    assert "A2A-Extensions" not in response.headers
    dummy.list_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_extension_notification_without_activation_is_not_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    dummy.list_sessions = AsyncMock(side_effect=AssertionError("should not be called"))  # type: ignore[method-assign]
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "method": "codex.sessions.list",
                "params": {"limit": 5},
            },
        )

    assert response.status_code == 204
    assert "A2A-Extensions" not in response.headers
    dummy.list_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_activated_extension_rejects_array_params_and_echoes_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    dummy.list_sessions = AsyncMock(side_effect=AssertionError("should not be called"))  # type: ignore[method-assign]
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 33,
                "method": "codex.sessions.list",
                "params": [],
            },
        )

    assert response.json()["error"]["code"] == -32602
    assert response.headers["A2A-Extensions"] == SESSION_QUERY_EXTENSION_URI
    dummy.list_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_activated_extension_notification_with_array_params_is_not_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    dummy.list_sessions = AsyncMock(side_effect=AssertionError("should not be called"))  # type: ignore[method-assign]
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "method": "codex.sessions.list",
                "params": [],
            },
        )

    assert response.status_code == 204
    assert response.headers["A2A-Extensions"] == SESSION_QUERY_EXTENSION_URI
    dummy.list_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_activated_extension_notification_echoes_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "method": "codex.sessions.list",
                "params": {"limit": 5},
            },
        )

    assert response.status_code == 204
    assert response.headers["A2A-Extensions"] == SESSION_QUERY_EXTENSION_URI
    assert dummy.last_sessions_params == {"limit": 5}


@pytest.mark.asyncio
async def test_interrupt_recovery_uses_its_declared_extension_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={
                "Authorization": "Bearer t-1",
                "A2A-Extensions": INTERRUPT_RECOVERY_EXTENSION_URI,
            },
            json={
                "jsonrpc": "2.0",
                "id": 32,
                "method": "codex.interrupts.list",
                "params": {},
            },
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"items": []}
    assert response.headers["A2A-Extensions"] == INTERRUPT_RECOVERY_EXTENSION_URI


@pytest.mark.asyncio
async def test_session_query_surfaces_upstream_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenClient(DummyCodexClient):
        async def list_sessions(self, *, params=None):
            del params
            raise RuntimeError("boom")

    dummy = BrokenClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers=_EXTENSION_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "codex.sessions.list",
                "params": {"limit": 5},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == InternalError().code
    assert payload["error"]["message"] == "Internal error"
    assert response.headers["A2A-Extensions"] == SESSION_QUERY_EXTENSION_URI


@pytest.mark.asyncio
async def test_removed_session_control_methods_do_not_call_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = DummyCodexClient(
        make_settings(
            a2a_bearer_token="t-1",
            a2a_log_payloads=False,
            **_BASE_SETTINGS,
        )
    )
    dummy.list_sessions = AsyncMock(side_effect=AssertionError("should not be called"))  # type: ignore[method-assign]
    app = _build_app(monkeypatch, dummy)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "codex.sessions.prompt_async",
                "params": {
                    "session_id": "s-1",
                    "request": {"parts": [{"type": "text", "text": "hello"}]},
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601
    dummy.list_sessions.assert_not_awaited()
