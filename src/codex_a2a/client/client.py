from __future__ import annotations

import httpx

from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.types import AgentCard, Message, Task
from a2a.types import MessageSendConfiguration

from .config import A2AClientConfig
from .errors import (
    A2AClientConfigError,
    A2AClientLifecycleError,
    A2AClientError,
    map_a2a_sdk_error,
)
from .types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


class A2AClient:
    """Minimal client facade for consuming A2A agents."""

    def __init__(
        self,
        config: A2AClientConfig,
        *,
        httpx_client: httpx.AsyncClient | None = None,
        card_resolver_factory=A2ACardResolver,
        client_factory_type=ClientFactory,
    ) -> None:
        if not config.agent_url:
            raise A2AClientConfigError("agent_url is required")

        self._config = config
        self._httpx_client = httpx_client or httpx.AsyncClient(
            timeout=self._build_timeout(),
            headers=config.default_headers,
        )
        self._owns_http_client = httpx_client is None
        self._closed = False
        self._card: AgentCard | None = None
        self._sdk_client: Client | None = None
        self._card_resolver_factory = card_resolver_factory
        self._client_factory_type = client_factory_type
        self._client_config = ClientConfig(
            streaming=False,
            supported_transports=list(config.supported_transports),
            use_client_preference=config.use_client_preference,
            httpx_client=self._httpx_client,
            accepted_output_modes=config.accepted_output_modes,
            extensions=config.extensions,
        )

    def _build_timeout(self) -> httpx.Timeout | None:
        if self._config.request_timeout_seconds is None:
            return None
        return httpx.Timeout(self._config.request_timeout_seconds)

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> "A2AClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def get_agent_card(self) -> AgentCard:
        return await self._get_agent_card()

    async def send(self, request: A2ASendRequest) -> Task | Message:
        client = await self._get_client()
        message = request.to_message()
        configuration: MessageSendConfiguration = request.to_send_configuration()

        response: Task | Message | None = None
        try:
            async for item in client.send_message(
                message,
                configuration=configuration,
                request_metadata=request.metadata,
            ):
                if isinstance(item, tuple):
                    response = item[0]
                else:
                    response = item
        except Exception as exc:
            raise map_a2a_sdk_error(exc) from exc

        if response is None:
            raise A2AClientError("A2A send_message returned no response")
        return response

    async def get_task(self, request: A2AGetTaskRequest) -> Task:
        client = await self._get_client()
        try:
            return await client.get_task(
                request.to_task_query(),
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc) from exc

    async def cancel(self, request: A2ACancelTaskRequest) -> Task:
        client = await self._get_client()
        try:
            return await client.cancel_task(
                request.to_task_id(),
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc) from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._sdk_client is not None:
            await self._sdk_client.close()
            self._sdk_client = None

        if self._owns_http_client and self._config.close_http_client:
            await self._httpx_client.aclose()

        self._card = None

    async def _get_agent_card(self) -> AgentCard:
        if self._card is not None:
            return self._card

        if self._closed:
            raise A2AClientLifecycleError("client is closed")

        resolver = self._card_resolver_factory(
            self._httpx_client,
            self._config.resolved_agent_url(),
            self._config.agent_card_path,
        )
        try:
            self._card = await resolver.get_agent_card()
        except Exception as exc:
            raise map_a2a_sdk_error(exc) from exc
        return self._card

    async def _get_client(self) -> Client:
        if self._closed:
            raise A2AClientLifecycleError("client is closed")
        if self._sdk_client is not None:
            return self._sdk_client

        card = await self._get_agent_card()
        try:
            factory = self._client_factory_type(self._client_config)
            self._sdk_client = factory.create(card)
            return self._sdk_client
        except Exception as exc:
            raise map_a2a_sdk_error(exc) from exc
