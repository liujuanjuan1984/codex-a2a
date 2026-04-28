"""Simple in-process cache for A2A client instances."""

from __future__ import annotations

import asyncio

from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import (
    SESSION_BINDING_EXTENSION_URI,
    STREAMING_EXTENSION_URI,
)

from .client import A2AClient
from .config import A2AClientConfig
from .request_context import build_default_headers


class A2AClientManager:
    """Cache `A2AClient` instances by normalized agent URL."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory=A2AClient,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._clients: dict[str, A2AClient] = {}
        self._lock = asyncio.Lock()

    def _build_headers(self) -> dict[str, str]:
        return build_default_headers(
            self._settings.a2a_client_bearer_token,
            self._settings.a2a_client_basic_auth,
        )

    def _build_config(self, agent_url: str) -> A2AClientConfig:
        return A2AClientConfig(
            agent_url=agent_url,
            request_timeout_seconds=self._settings.a2a_client_timeout_seconds,
            card_fetch_timeout_seconds=self._settings.a2a_client_card_fetch_timeout_seconds,
            use_client_preference=self._settings.a2a_client_use_client_preference,
            default_headers=self._build_headers(),
            supported_transports=list(self._settings.a2a_client_supported_transports),
            accepted_output_modes=["text/plain"],
            extensions=[
                SESSION_BINDING_EXTENSION_URI,
                STREAMING_EXTENSION_URI,
            ],
        )

    async def get_client(self, agent_url: str) -> A2AClient:
        normalized = agent_url.rstrip("/")
        if not normalized:
            raise ValueError("agent_url is required")
        async with self._lock:
            client = self._clients.get(normalized)
            if client is not None:
                return client
            client = self._client_factory(self._build_config(normalized))
            self._clients[normalized] = client
            return client

    async def close_all(self) -> None:
        async with self._lock:
            for client in self._clients.values():
                await client.close()
            self._clients.clear()
