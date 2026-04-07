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
async def test_thread_lifecycle_extension_routes_control_methods(monkeypatch) -> None:
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
        fork_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 401,
                "method": "codex.threads.fork",
                "params": {
                    "thread_id": "thr-1",
                    "request": {"ephemeral": True},
                    "metadata": {"codex": {"directory": "/workspace"}},
                },
            },
        )
        archive_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 402,
                "method": "codex.threads.archive",
                "params": {"thread_id": "thr-1"},
            },
        )
        unarchive_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 403,
                "method": "codex.threads.unarchive",
                "params": {"thread_id": "thr-1"},
            },
        )
        metadata_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 404,
                "method": "codex.threads.metadata.update",
                "params": {
                    "thread_id": "thr-1",
                    "request": {"gitInfo": {"branch": "feat/thread-lifecycle"}},
                },
            },
        )

    assert fork_response.json()["result"]["thread_id"] == "thr-1-fork"
    assert fork_response.json()["result"]["thread"]["title"] == "Fork of thr-1"
    assert dummy.last_thread_fork == {
        "thread_id": "thr-1",
        "params": {"ephemeral": True},
    }

    assert archive_response.json()["result"] == {"ok": True, "thread_id": "thr-1"}
    assert dummy.last_thread_archive == {"thread_id": "thr-1"}

    assert unarchive_response.json()["result"]["thread_id"] == "thr-1"
    assert unarchive_response.json()["result"]["thread"]["title"] == "Restored thr-1"
    assert dummy.last_thread_unarchive == {"thread_id": "thr-1"}

    assert metadata_response.json()["result"]["thread_id"] == "thr-1"
    assert metadata_response.json()["result"]["thread"]["raw"]["gitInfo"]["branch"] == (
        "feat/thread-lifecycle"
    )
    assert dummy.last_thread_metadata_update == {
        "thread_id": "thr-1",
        "params": {"gitInfo": {"branch": "feat/thread-lifecycle"}},
    }


@pytest.mark.asyncio
async def test_thread_lifecycle_watch_routes_to_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_thread_lifecycle_runtime.start = AsyncMock(
        return_value={"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 405,
                "method": "codex.threads.watch",
                "params": {
                    "request": {
                        "events": ["thread.started", "thread.status.changed"],
                        "threadIds": ["thr-1"],
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    app.state.codex_thread_lifecycle_runtime.start.assert_awaited_once()
    kwargs = app.state.codex_thread_lifecycle_runtime.start.await_args.kwargs
    assert kwargs["request"] == {
        "events": ["thread.started", "thread.status.changed"],
        "threadIds": ["thr-1"],
    }
    assert kwargs["context"] is not None


@pytest.mark.asyncio
async def test_thread_lifecycle_watch_release_routes_to_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_thread_lifecycle_runtime.release = AsyncMock(
        return_value={
            "ok": True,
            "task_id": "task-1",
            "owner_status": "released",
            "release_reason": "task_cancel",
            "subscription_key": "sub-1",
            "remaining_owner_count": 0,
            "subscription_released": True,
        }
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 406,
                "method": "codex.threads.watch.release",
                "params": {"task_id": "task-1"},
            },
        )

    assert response.status_code == 200
    assert response.json()["result"]["task_id"] == "task-1"
    app.state.codex_thread_lifecycle_runtime.release.assert_awaited_once()
    kwargs = app.state.codex_thread_lifecycle_runtime.release.await_args.kwargs
    assert kwargs["task_id"] == "task-1"
    assert kwargs["context"] is not None


@pytest.mark.asyncio
async def test_thread_lifecycle_extension_rejects_invalid_request_shapes(monkeypatch) -> None:
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
        fork_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 406,
                "method": "codex.threads.fork",
                "params": {"thread_id": "thr-1", "request": {"ephemeral": "yes"}},
            },
        )
        metadata_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 407,
                "method": "codex.threads.metadata.update",
                "params": {"thread_id": "thr-1", "request": {"gitInfo": {}}},
            },
        )
        watch_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 408,
                "method": "codex.threads.watch",
                "params": {"request": {"events": ["thread.deleted"]}},
            },
        )
        watch_release_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 409,
                "method": "codex.threads.watch.release",
                "params": {"task_id": "   "},
            },
        )

    assert fork_response.json()["error"]["code"] == -32602
    assert fork_response.json()["error"]["data"]["field"] == "request.ephemeral"
    assert metadata_response.json()["error"]["code"] == -32602
    assert metadata_response.json()["error"]["data"]["field"] == "request.git_info"
    assert watch_response.json()["error"]["code"] == -32602
    assert watch_response.json()["error"]["data"]["field"] == "request.events"
    assert watch_release_response.json()["error"]["code"] == -32602
    assert watch_release_response.json()["error"]["data"]["field"] == "task_id"


@pytest.mark.asyncio
async def test_thread_lifecycle_watch_release_maps_not_found_and_forbidden(monkeypatch) -> None:
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
        app.state.codex_thread_lifecycle_runtime.release = AsyncMock(
            side_effect=LookupError("task-404")
        )
        not_found_response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 410,
                "method": "codex.threads.watch.release",
                "params": {"task_id": "task-404"},
            },
        )

        app.state.codex_thread_lifecycle_runtime.release = AsyncMock(
            side_effect=PermissionError("task-403")
        )
        forbidden_response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 411,
                "method": "codex.threads.watch.release",
                "params": {"task_id": "task-403"},
            },
        )

    assert not_found_response.json()["error"]["code"] == -32014
    assert not_found_response.json()["error"]["data"] == {
        "type": "WATCH_NOT_FOUND",
        "task_id": "task-404",
    }
    assert forbidden_response.json()["error"]["code"] == -32015
    assert forbidden_response.json()["error"]["data"] == {
        "type": "WATCH_FORBIDDEN",
        "task_id": "task-403",
    }
