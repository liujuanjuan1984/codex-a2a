from __future__ import annotations

import pytest

from codex_a2a.client import A2AClientConfig, A2AClientManager
from codex_a2a.contracts.extensions import SESSION_BINDING_EXTENSION_URI, STREAMING_EXTENSION_URI
from tests.support.settings import make_settings


class _FakeA2AClient:
    def __init__(self, config: A2AClientConfig) -> None:
        self.config = config
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self) -> None:
        self.created: list[A2AClientConfig] = []

    def __call__(self, config: A2AClientConfig) -> _FakeA2AClient:
        client = _FakeA2AClient(config)
        self.created.append(config)
        return client


@pytest.mark.asyncio
async def test_manager_normalizes_config_and_transports() -> None:
    settings = make_settings(
        a2a_client_timeout_seconds=41.0,
        a2a_client_card_fetch_timeout_seconds=7.0,
        a2a_client_use_client_preference=True,
        a2a_client_bearer_token="peer-token",
        a2a_client_supported_transports=("http-json", "json-rpc"),
    )
    factory = _Factory()
    manager = A2AClientManager(settings, client_factory=factory)
    client = await manager.get_client("https://peer.example.com/")

    assert client.config.request_timeout_seconds == 41.0
    assert client.config.card_fetch_timeout_seconds == 7.0
    assert client.config.use_client_preference is True
    assert client.config.default_headers == {"Authorization": "Bearer peer-token"}
    assert client.config.supported_transports == ["HTTP+JSON", "JSONRPC"]
    assert client.config.extensions == [
        SESSION_BINDING_EXTENSION_URI,
        STREAMING_EXTENSION_URI,
    ]


@pytest.mark.asyncio
async def test_manager_uses_basic_auth_when_bearer_is_absent() -> None:
    settings = make_settings(
        a2a_client_basic_auth="user:pass",
    )
    factory = _Factory()
    manager = A2AClientManager(settings, client_factory=factory)
    client = await manager.get_client("https://peer.example.com/")

    assert client.config.default_headers == {"Authorization": "Basic dXNlcjpwYXNz"}


@pytest.mark.asyncio
async def test_manager_caches_client_by_normalized_url() -> None:
    settings = make_settings()
    factory = _Factory()
    manager = A2AClientManager(settings, client_factory=factory)

    c1 = await manager.get_client("https://peer.example.com/")
    c2 = await manager.get_client("https://peer.example.com")

    assert c1 is c2
    assert len(factory.created) == 1

    await manager.close_all()
    assert c1.closed
