from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol, cast
from uuid import uuid4

import httpx
from a2a.client import (
    A2ACardResolver,
    ClientCallContext,
    ClientConfig,
    create_client,
)
from a2a.client.auth.credentials import CredentialService
from a2a.client.auth.interceptor import AuthInterceptor
from a2a.client.interceptors import ClientCallInterceptor
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
)

from codex_a2a.a2a_proto import new_text_part, proto_clone, to_struct

from .agent_card import build_agent_card_request_kwargs, resolve_agent_card_endpoint
from .auth import StaticCredentialService
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
from .types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


class _SDKClientProtocol(Protocol):
    def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncIterator[StreamResponse]: ...

    async def get_task(
        self,
        request: GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task: ...

    async def cancel_task(
        self,
        request: CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task: ...


class A2AClient:
    """Factory-style facade for lightweight A2A client bootstrap and calls."""

    def __init__(
        self,
        config: A2AClientConfig,
        *,
        httpx_client: httpx.AsyncClient | None = None,
        card_resolver_factory=A2ACardResolver,
        client_creator=create_client,
        credential_service: CredentialService | None = None,
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
        self._client_creator = client_creator
        self._credential_service = credential_service
        self._client_config = ClientConfig(
            streaming=True,
            supported_protocol_bindings=list(config.supported_transports),
            use_client_preference=config.use_client_preference,
            httpx_client=self._httpx_client,
            accepted_output_modes=config.accepted_output_modes,
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
        text: str | None = None,
        *,
        parts: Sequence[Part] | None = None,
        message: Message | None = None,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        accepted_output_modes: list[str] | None = None,
        history_length: int | None = None,
        blocking: bool = True,
    ) -> AsyncIterator[StreamResponse]:
        client = await self._get_client()
        sdk_client = client
        outbound_message = self._build_outbound_message(
            text=text,
            parts=parts,
            message=message,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
        )
        request_metadata, extra_headers = split_request_metadata(metadata)

        configuration_kwargs: dict[str, Any] = {"return_immediately": not blocking}
        if accepted_output_modes is not None:
            configuration_kwargs["accepted_output_modes"] = accepted_output_modes
        if history_length is not None:
            configuration_kwargs["history_length"] = history_length
        request_configuration = SendMessageConfiguration(**configuration_kwargs)
        send_request = SendMessageRequest(
            message=outbound_message,
            configuration=request_configuration,
        )
        request_metadata_struct = to_struct(request_metadata or None)
        if request_metadata_struct is not None:
            send_request.metadata.CopyFrom(request_metadata_struct)
        try:
            async for item in sdk_client.send_message(
                send_request,
                context=build_call_context(extra_headers),
            ):
                yield item
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="SendMessage") from exc

    async def send(self, request: A2ASendRequest) -> StreamResponse:
        last_event: StreamResponse | None = None
        async for item in self.send_message(
            request.text,
            parts=request.parts,
            message=request.message,
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
        _request_metadata, extra_headers = split_request_metadata(request.metadata)
        try:
            task_request = GetTaskRequest(
                id=request.task_id,
                history_length=request.history_length,
            )
            return await sdk_client.get_task(
                task_request,
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
            cancel_request = CancelTaskRequest(id=request.task_id)
            metadata_struct = to_struct(request_metadata or None)
            if metadata_struct is not None:
                cancel_request.metadata.CopyFrom(metadata_struct)
            return await sdk_client.cancel_task(
                cancel_request,
                context=build_call_context(extra_headers),
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="tasks/cancel") from exc

    async def cancel_task(self, task_id: str, *, metadata: Mapping[str, Any] | None = None) -> Task:
        return await self.cancel(
            A2ACancelTaskRequest(task_id=task_id, metadata=dict(metadata) if metadata else None)
        )

    @staticmethod
    def extract_text(event: StreamResponse) -> str:
        extracted = extract_text_from_payload(event)
        return extracted or ""

    async def _get_agent_card(self) -> AgentCard:
        if self._card is not None:
            return self._card

        if self._closed:
            raise A2AClientLifecycleError("client is closed")

        cached_card = self._extract_sdk_client_card()
        if cached_card is not None:
            self._card = cached_card
            return self._card

        async with self._lock:
            if self._card is not None:
                return self._card

            cached_card = self._extract_sdk_client_card()
            if cached_card is not None:
                self._card = cached_card
                return self._card

            endpoint = resolve_agent_card_endpoint(self._config)
            resolver = self._card_resolver_factory(
                self._httpx_client,
                endpoint.base_url,
                endpoint.agent_card_path,
            )
            try:
                self._card = await resolver.get_agent_card(
                    http_kwargs=build_agent_card_request_kwargs(self._config)
                )
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
        endpoint = resolve_agent_card_endpoint(self._config)
        interceptors = self._build_interceptors()
        agent_or_card: str | AgentCard = endpoint.base_url
        client_kwargs: dict[str, Any] = {
            "client_config": self._client_config,
            "interceptors": interceptors or None,
        }
        if self._card is not None:
            agent_or_card = cast(AgentCard, proto_clone(self._card))
        else:
            client_kwargs["relative_card_path"] = endpoint.agent_card_path
            client_kwargs["resolver_http_kwargs"] = build_agent_card_request_kwargs(self._config)
        try:
            self._sdk_client = await self._client_creator(agent_or_card, **client_kwargs)
        except ValueError as exc:
            raise A2AUnsupportedBindingError(
                f"Unable to bind A2A client to peer transport: {exc}"
            ) from exc
        except Exception as exc:
            mapped_error = map_a2a_sdk_error(exc, operation="agent_card")
            if type(mapped_error) is A2AClientError:
                raise A2AClientError(f"Failed to initialize A2A client: {exc}") from exc
            raise mapped_error from exc
        if self._sdk_client is None:
            raise A2AClientError("Failed to initialize A2A client")
        cached_card = self._extract_sdk_client_card()
        if cached_card is not None:
            self._card = cached_card
        return self._sdk_client

    def _extract_sdk_client_card(self) -> AgentCard | None:
        if self._sdk_client is None:
            return None
        agent_card = getattr(cast(Any, self._sdk_client), "_card", None)
        if agent_card is None:
            return None
        return cast(AgentCard, proto_clone(cast(AgentCard, agent_card)))

    def _build_interceptors(self) -> list[ClientCallInterceptor]:
        interceptors: list[ClientCallInterceptor] = []
        credential_service = self._credential_service
        if credential_service is None and self._config.auth_credentials:
            credential_service = StaticCredentialService(self._config.auth_credentials)
        if credential_service is not None:
            interceptors.append(AuthInterceptor(credential_service))
        return interceptors

    def _build_outbound_message(
        self,
        *,
        text: str | None,
        parts: Sequence[Part] | None,
        message: Message | None,
        context_id: str | None,
        task_id: str | None,
        message_id: str | None,
    ) -> Message:
        payload_count = sum(value is not None for value in (text, parts, message))
        if payload_count != 1:
            raise ValueError("Exactly one of text, parts, or message must be provided")

        if message is not None:
            if any(value is not None for value in (context_id, task_id, message_id)):
                raise ValueError(
                    "context_id, task_id, and message_id cannot be combined with message"
                )
            return cast(Message, proto_clone(message))

        if parts is not None:
            if not parts:
                raise ValueError("parts must not be empty")
            outbound_parts = [cast(Part, proto_clone(part)) for part in parts]
        else:
            assert text is not None
            outbound_parts = [new_text_part(text)]

        return Message(
            message_id=message_id or f"msg-{uuid4().hex[:12]}",
            role=Role.ROLE_USER,
            context_id=context_id,
            task_id=task_id,
            parts=outbound_parts,
            metadata=None,
        )
