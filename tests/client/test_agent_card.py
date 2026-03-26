from __future__ import annotations

import httpx
import pytest

from codex_a2a.client.agent_card import (
    AgentCardEndpoint,
    build_agent_card_request_kwargs,
    resolve_agent_card_endpoint,
)
from codex_a2a.client.config import A2AClientConfig
from codex_a2a.client.errors import A2AClientConfigError


def test_resolve_agent_card_endpoint_normalizes_explicit_well_known_path() -> None:
    endpoint = resolve_agent_card_endpoint(
        A2AClientConfig(agent_url="https://ops.example.com/tenant/.well-known/agent-card.json")
    )

    assert endpoint == AgentCardEndpoint(
        base_url="https://ops.example.com/tenant",
        agent_card_path="/.well-known/agent-card.json",
    )


def test_resolve_agent_card_endpoint_rejects_relative_agent_url() -> None:
    with pytest.raises(A2AClientConfigError, match="absolute URL"):
        resolve_agent_card_endpoint(A2AClientConfig(agent_url="/relative/path"))


def test_build_agent_card_request_kwargs_includes_timeout_and_headers() -> None:
    config = A2AClientConfig(
        agent_url="https://example.org",
        card_fetch_timeout_seconds=7.5,
        default_headers={"Authorization": "Bearer peer-token"},
    )

    http_kwargs = build_agent_card_request_kwargs(config)

    timeout = http_kwargs.get("timeout")
    assert timeout is not None
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 7.5
    assert http_kwargs["headers"] == {"Authorization": "Bearer peer-token"}


def test_build_agent_card_request_kwargs_supports_basic_auth_header() -> None:
    config = A2AClientConfig(
        agent_url="https://example.org",
        default_headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )

    http_kwargs = build_agent_card_request_kwargs(config)

    assert http_kwargs["headers"] == {"Authorization": "Basic dXNlcjpwYXNz"}
