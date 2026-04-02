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
async def test_exec_start_routes_to_exec_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_exec_runtime.start = AsyncMock(
        return_value={
            "ok": True,
            "task_id": "task-1",
            "context_id": "ctx-1",
            "process_id": "exec-1",
        }
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 201,
                "method": "codex.exec.start",
                "params": {
                    "request": {
                        "command": "bash",
                        "arguments": "-lc 'printf hello'",
                        "processId": "exec-1",
                        "tty": True,
                        "rows": 24,
                        "cols": 80,
                    },
                    "metadata": {"codex": {"directory": "/workspace"}},
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] == {
        "ok": True,
        "task_id": "task-1",
        "context_id": "ctx-1",
        "process_id": "exec-1",
    }
    app.state.codex_exec_runtime.start.assert_awaited_once()
    kwargs = app.state.codex_exec_runtime.start.await_args.kwargs
    assert kwargs["request"] == {
        "command": "bash",
        "arguments": "-lc 'printf hello'",
        "processId": "exec-1",
        "tty": True,
        "rows": 24,
        "cols": 80,
    }
    assert kwargs["directory"] == "/workspace"
    assert kwargs["context"] is not None


@pytest.mark.asyncio
async def test_exec_write_resize_and_terminate_route_to_exec_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_exec_runtime.write = AsyncMock(
        return_value={"ok": True, "process_id": "exec-1"}
    )
    app.state.codex_exec_runtime.resize = AsyncMock(
        return_value={"ok": True, "process_id": "exec-1"}
    )
    app.state.codex_exec_runtime.terminate = AsyncMock(
        return_value={"ok": True, "process_id": "exec-1"}
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer t-1"}
        write_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 202,
                "method": "codex.exec.write",
                "params": {"request": {"processId": "exec-1", "deltaBase64": "cHdkCg=="}},
            },
        )
        resize_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 203,
                "method": "codex.exec.resize",
                "params": {"request": {"processId": "exec-1", "rows": 40, "cols": 120}},
            },
        )
        terminate_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 204,
                "method": "codex.exec.terminate",
                "params": {"request": {"processId": "exec-1"}},
            },
        )

    assert write_response.json()["result"] == {"ok": True, "process_id": "exec-1"}
    assert resize_response.json()["result"] == {"ok": True, "process_id": "exec-1"}
    assert terminate_response.json()["result"] == {"ok": True, "process_id": "exec-1"}
    app.state.codex_exec_runtime.write.assert_awaited_once_with(
        process_id="exec-1",
        delta_base64="cHdkCg==",
        close_stdin=None,
    )
    app.state.codex_exec_runtime.resize.assert_awaited_once_with(
        process_id="exec-1",
        rows=40,
        cols=120,
    )
    app.state.codex_exec_runtime.terminate.assert_awaited_once_with(process_id="exec-1")


@pytest.mark.asyncio
async def test_exec_control_rejects_invalid_request_shapes(monkeypatch) -> None:
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
        start_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 205,
                "method": "codex.exec.start",
                "params": {"request": {"command": "   "}},
            },
        )
        write_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 206,
                "method": "codex.exec.write",
                "params": {"request": {"processId": "exec-1"}},
            },
        )
        resize_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 207,
                "method": "codex.exec.resize",
                "params": {"request": {"processId": "exec-1", "rows": 0, "cols": 120}},
            },
        )

    assert start_response.json()["error"]["code"] == -32602
    assert start_response.json()["error"]["data"]["field"] == "request.command"
    assert write_response.json()["error"]["code"] == -32602
    assert write_response.json()["error"]["data"]["field"] == "request.close_stdin"
    assert resize_response.json()["error"]["code"] == -32602
    assert resize_response.json()["error"]["data"]["field"] == "request.rows"


@pytest.mark.asyncio
async def test_exec_control_maps_missing_session_lookup_to_business_error(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_exec_runtime.write = AsyncMock(side_effect=LookupError("Unknown exec session"))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 208,
                "method": "codex.exec.write",
                "params": {"request": {"processId": "exec-missing", "closeStdin": True}},
            },
        )

    payload = response.json()
    assert payload["error"]["code"] == -32009
    assert payload["error"]["data"]["type"] == "EXEC_SESSION_NOT_FOUND"
    assert payload["error"]["data"]["process_id"] == "exec-missing"
