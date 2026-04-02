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
async def test_discovery_extension_routes_read_only_methods(monkeypatch) -> None:
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
        skills_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 301,
                "method": "codex.discovery.skills.list",
                "params": {"cwds": ["/workspace/project"], "forceReload": True},
            },
        )
        apps_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 302,
                "method": "codex.discovery.apps.list",
                "params": {"limit": 20, "forceRefetch": False},
            },
        )
        plugins_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 303,
                "method": "codex.discovery.plugins.list",
                "params": {"cwds": ["/workspace/project"], "forceRemoteSync": False},
            },
        )
        plugin_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 304,
                "method": "codex.discovery.plugins.read",
                "params": {
                    "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
                    "pluginName": "sample",
                },
            },
        )

    assert skills_response.status_code == 200
    assert skills_response.json()["result"]["items"][0]["skills"][0]["path"].endswith("SKILL.md")
    assert dummy.last_skills_params == {
        "cwds": ["/workspace/project"],
        "forceReload": True,
    }

    assert apps_response.status_code == 200
    assert apps_response.json()["result"]["items"][0]["mention_path"] == "app://demo-app"
    assert dummy.last_apps_params == {"limit": 20, "forceRefetch": False}

    assert plugins_response.status_code == 200
    plugin_summary = plugins_response.json()["result"]["items"][0]["plugins"][0]
    assert plugin_summary["mention_path"] == "plugin://sample@test"
    assert dummy.last_plugins_params == {
        "cwds": ["/workspace/project"],
        "forceRemoteSync": False,
    }

    assert plugin_response.status_code == 200
    assert plugin_response.json()["result"]["item"]["mention_path"] == "plugin://sample@test"
    assert dummy.last_plugin_read_params == {
        "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
        "pluginName": "sample",
    }


@pytest.mark.asyncio
async def test_discovery_watch_routes_to_runtime(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    dummy = DummyCodexClient(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = app_module.create_app(
        make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, **_BASE_SETTINGS)
    )

    app.state.codex_discovery_runtime.start = AsyncMock(
        return_value={"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={
                "jsonrpc": "2.0",
                "id": 308,
                "method": "codex.discovery.watch",
                "params": {"request": {"events": ["skills.changed"]}},
            },
        )

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "task_id": "task-1", "context_id": "ctx-1"}
    app.state.codex_discovery_runtime.start.assert_awaited_once()
    kwargs = app.state.codex_discovery_runtime.start.await_args.kwargs
    assert kwargs["request"] == {"events": ["skills.changed"]}
    assert kwargs["context"] is not None


@pytest.mark.asyncio
async def test_discovery_extension_rejects_invalid_request_shapes(monkeypatch) -> None:
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
        skills_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 305,
                "method": "codex.discovery.skills.list",
                "params": {"cwds": [""], "forceReload": True},
            },
        )
        apps_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 306,
                "method": "codex.discovery.apps.list",
                "params": {"limit": 0},
            },
        )
        plugin_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 307,
                "method": "codex.discovery.plugins.read",
                "params": {"marketplacePath": "", "pluginName": "sample"},
            },
        )
        watch_response = await client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 308,
                "method": "codex.discovery.watch",
                "params": {"request": {"events": []}},
            },
        )

    assert skills_response.json()["error"]["code"] == -32602
    assert skills_response.json()["error"]["data"]["field"] == "cwds"
    assert apps_response.json()["error"]["code"] == -32602
    assert apps_response.json()["error"]["data"]["field"] == "limit"
    assert plugin_response.json()["error"]["code"] == -32602
    assert plugin_response.json()["error"]["data"]["field"] == "marketplace_path"
    assert watch_response.json()["error"]["code"] == -32602
    assert watch_response.json()["error"]["data"]["field"] == "request.events"
