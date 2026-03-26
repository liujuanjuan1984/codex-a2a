from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, cast
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.middleware import ClientCallContext, ClientCallInterceptor
from a2a.types import (
    AgentCard,
    Message,
    MessageSendConfiguration,
    Part,
    Role,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TextPart,
)

from .agent_card import build_agent_card_request_kwargs, resolve_agent_card_endpoint
from .config import A2AClientConfig
from .errors import (
    A2AClientConfigError,
    A2AClientError,
    A2AClientLifecycleError,
    A2AUnsupportedBindingError,
    map_a2a_sdk_error,
)
from .payload_text import extract_text_from_payload
from .request_context import build_call_context, split_request_metadata
from .types import A2ACancelTaskRequest, A2AClientEvent, A2AGetTaskRequest, A2ASendRequest


class _SDKClientProtocol(Protocol):
    def send_message(
        self,
        request: Message,
        *,
        configuration: MessageSendConfiguration | None = None,
        context: ClientCallContext | None = None,
        request_metadata: dict[str, Any] | None = None,
        extensions: list[str] | None = None,
    ) -> AsyncIterator[A2AClientEvent]: ...

    async def get_task(
        self,
        request: TaskQueryParams,
        *,
        context: ClientCallContext | None = None,
        extensions: list[str] | None = None,
    ) -> Task: ...

    async def cancel_task(
        self,
        request: TaskIdParams,
        *,
        context: ClientCallContext | None = None,
        extensions: list[str] | None = None,
    ) -> Task: ...


class _HeaderInterceptor(ClientCallInterceptor):
    def __init__(self, default_headers: Mapping[str, str] | None = None) -> None:
        self._default_headers = {
            key: value for key, value in dict(default_headers or {}).items() if value is not None
        }

    async def intercept(
        self,
        _method_name: str,
        _request_payload: dict[str, Any],
        http_kwargs: dict[str, Any],
        _agent_card: object | None,
        context: ClientCallContext | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        headers = dict(http_kwargs.get("headers") or {})
        headers.update(self._default_headers)

        if context is not None:
            dynamic_headers = getattr(context.state, "headers", None)
            if dynamic_headers is None and isinstance(context.state, Mapping):
                dynamic_headers = context.state.get("headers")
            if isinstance(dynamic_headers, Mapping):
                for key, value in dynamic_headers.items():
                    if isinstance(key, str) and value is not None:
                        headers[key] = str(value)

        if headers:
            http_kwargs["headers"] = headers
        return _request_payload, http_kwargs


class A2AClient:
    """Factory-style facade for lightweight A2A client bootstrap and calls."""

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
        self._sdk_client: _SDKClientProtocol | None = None
        self._card_resolver_factory = card_resolver_factory
        self._client_factory_type = client_factory_type
        self._client_config = ClientConfig(
            streaming=True,
            supported_transports=list(config.supported_transports),
            use_client_preference=config.use_client_preference,
            httpx_client=self._httpx_client,
            accepted_output_modes=config.accepted_output_modes,
            extensions=config.extensions,
        )
        self._lock = asyncio.Lock()

    def _build_timeout(self) -> httpx.Timeout | None:
        if self._config.request_timeout_seconds is None:
            return None
        return httpx.Timeout(self._config.request_timeout_seconds)

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> A2AClient:
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._sdk_client is not None:
            closer = getattr(cast(Any, self._sdk_client), "close", None)
            if callable(closer):
                await closer()
            self._sdk_client = None

        if self._owns_http_client and self._config.close_http_client:
            await self._httpx_client.aclose()

        self._card = None

    async def get_agent_card(self) -> AgentCard:
        return await self._get_agent_card()

    async def send_message(
        self,
        text: str,
        *,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        extensions: list[str] | None = None,
        accepted_output_modes: list[str] | None = None,
        history_length: int | None = None,
        blocking: bool = True,
    ) -> AsyncIterator[A2AClientEvent]:
        client = await self._get_client()
        sdk_client = client
        request = self._build_user_message(
            text=text,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
        )
        request_metadata, extra_headers = split_request_metadata(metadata)

        configuration_kwargs: dict[str, Any] = {"blocking": blocking}
        if accepted_output_modes is not None:
            configuration_kwargs["acceptedOutputModes"] = accepted_output_modes
        if history_length is not None:
            configuration_kwargs["historyLength"] = history_length
        request_configuration = MessageSendConfiguration(**configuration_kwargs)
        try:
            async for item in sdk_client.send_message(
                request,
                configuration=request_configuration,
                request_metadata=request_metadata or {},
                context=build_call_context(extra_headers),
                extensions=extensions,
            ):
                yield item
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="message/send") from exc

    async def send(self, request: A2ASendRequest) -> A2AClientEvent:
        last_event: A2AClientEvent | None = None
        async for item in self.send_message(
            request.text,
            context_id=request.context_id,
            task_id=request.task_id,
            message_id=request.message_id,
            metadata=request.metadata,
            accepted_output_modes=request.accepted_output_modes,
            history_length=request.history_length,
            blocking=request.blocking,
        ):
            last_event = item
        if last_event is None:
            raise A2AClientError("A2A send_message returned no response")
        return last_event

    async def get_task(self, request: A2AGetTaskRequest) -> Task:
        client = await self._get_client()
        sdk_client = client
        request_metadata, extra_headers = split_request_metadata(request.metadata)
        try:
            return await sdk_client.get_task(
                TaskQueryParams(
                    id=request.task_id,
                    history_length=request.history_length,
                    metadata=request_metadata or {},
                ),
                context=build_call_context(extra_headers),
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="tasks/get") from exc

    async def get_task_by_id(
        self,
        task_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Task:
        return await self.get_task(
            A2AGetTaskRequest(
                task_id=task_id,
                metadata=dict(metadata) if metadata is not None else None,
            )
        )

    async def cancel(self, request: A2ACancelTaskRequest) -> Task:
        client = await self._get_client()
        sdk_client = client
        request_metadata, extra_headers = split_request_metadata(request.metadata)
        try:
            return await sdk_client.cancel_task(
                TaskIdParams(id=request.task_id, metadata=request_metadata or {}),
                context=build_call_context(extra_headers),
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="tasks/cancel") from exc

    async def cancel_task(self, task_id: str, *, metadata: Mapping[str, Any] | None = None) -> Task:
        return await self.cancel(
            A2ACancelTaskRequest(task_id=task_id, metadata=dict(metadata) if metadata else None)
        )

    @staticmethod
    def extract_text(event: Task | Message | Any) -> str:
        extracted = extract_text_from_payload(event)
        return extracted or ""

    async def _get_agent_card(self) -> AgentCard:
        if self._card is not None:
            return self._card

        if self._closed:
            raise A2AClientLifecycleError("client is closed")

        endpoint = resolve_agent_card_endpoint(self._config)
        resolver = self._card_resolver_factory(
            self._httpx_client,
            endpoint.base_url,
            endpoint.agent_card_path,
        )
        try:
            try:
                self._card = await resolver.get_agent_card(
                    http_kwargs=build_agent_card_request_kwargs(self._config)
                )
            except TypeError:
                self._card = await resolver.get_agent_card()
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="agent_card") from exc
        return cast(AgentCard, self._card)

    async def _get_client(self) -> _SDKClientProtocol:
        if self._closed:
            raise A2AClientLifecycleError("client is closed")
        async with self._lock:
            if self._sdk_client is not None:
                return self._sdk_client
            return await self._build_client()

    async def _build_client(self) -> _SDKClientProtocol:
        card = await self._get_agent_card()
        try:
            factory = self._client_factory_type(self._client_config)
        except ValueError as exc:
            raise A2AUnsupportedBindingError(
                f"Unable to initialize A2A client with transport preference: {exc}"
            ) from exc
        except Exception as exc:
            raise A2AClientError(f"Unable to initialize A2A client factory: {exc}") from exc

        interceptors = self._build_interceptors()
        try:
            self._sdk_client = factory.create(card, interceptors=interceptors)
        except ValueError as exc:
            raise A2AUnsupportedBindingError(
                f"Unable to bind A2A client to peer transport: {exc}"
            ) from exc
        except TypeError:
            self._sdk_client = factory.create(card)
        if self._sdk_client is None:
            raise A2AClientError("Failed to initialize A2A client")
        return self._sdk_client

    def _build_interceptors(self) -> list[ClientCallInterceptor]:
        return [_HeaderInterceptor(self._config.default_headers)]

    def _build_user_message(
        self,
        *,
        text: str,
        context_id: str | None,
        task_id: str | None,
        message_id: str | None,
    ) -> Message:
        return Message(
            message_id=message_id or f"msg-{uuid4().hex[:12]}",
            role=Role.user,
            context_id=context_id,
            task_id=task_id,
            parts=[Part(root=TextPart(text=text))],
            metadata=None,
        )
