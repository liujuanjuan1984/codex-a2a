from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.client.middleware import ClientCallContext, ClientCallInterceptor
from a2a.types import (
    AgentCard,
    Message,
    MessageSendConfiguration,
    Part,
    Role,
    Task,
    TextPart,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from .config import A2AClientConfig
from .errors import (
    A2AClientConfigError,
    A2AClientError,
    A2AClientLifecycleError,
    A2AUnsupportedBindingError,
    map_a2a_sdk_error,
)
from .types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


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
        self._sdk_client: Client | None = None
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

    def _build_card_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self._config.card_fetch_timeout_seconds)

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> A2AClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

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
    ) -> AsyncIterator[Task | Message]:
        client = await self._get_client()
        request = self._build_user_message(
            text=text,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
        )
        request_metadata, extra_headers = self._split_request_metadata(metadata)

        configuration_kwargs: dict[str, Any] = {"blocking": blocking}
        if accepted_output_modes is not None:
            configuration_kwargs["acceptedOutputModes"] = accepted_output_modes
        if history_length is not None:
            configuration_kwargs["historyLength"] = history_length
        request_configuration = MessageSendConfiguration(**configuration_kwargs)
        try:
            async for item in client.send_message(
                request,
                configuration=request_configuration,
                request_metadata=request_metadata or {},
                context=self._build_call_context(extra_headers),
                extensions=extensions,
            ):
                yield item
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="message/send") from exc

    async def send(self, request: A2ASendRequest) -> Task | Message:
        last_event: Task | Message | None = None
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
        request_metadata, extra_headers = self._split_request_metadata(request.metadata)
        try:
            return await client.get_task(
                request.to_task_query(),
                context=self._build_call_context(extra_headers),
                request_metadata=request_metadata or {},
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
        request_metadata, extra_headers = self._split_request_metadata(request.metadata)
        try:
            return await client.cancel_task(
                request.to_task_id(),
                context=self._build_call_context(extra_headers),
                request_metadata=request_metadata or {},
            )
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="tasks/cancel") from exc

    async def cancel_task(self, task_id: str, *, metadata: Mapping[str, Any] | None = None) -> Task:
        return await self.cancel(
            A2ACancelTaskRequest(task_id=task_id, metadata=dict(metadata) if metadata else None)
        )

    @staticmethod
    def extract_text(event: Task | Message | Any) -> str:
        extracted = A2AClient._extract_text_from_payload(event)
        return extracted or ""

    def _resolve_agent_card_endpoint(self) -> tuple[str, str]:
        resolved_url = self._config.resolved_agent_url()
        parsed_url = urlsplit(resolved_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise A2AClientConfigError(f"agent_url must be absolute URL: {resolved_url}")

        normalized_no_leading = (parsed_url.path or "").rstrip("/").lstrip("/")
        candidate_paths = (
            AGENT_CARD_WELL_KNOWN_PATH,
            PREV_AGENT_CARD_WELL_KNOWN_PATH,
            EXTENDED_AGENT_CARD_PATH,
        )

        base_path = normalized_no_leading
        agent_card_path = self._config.agent_card_path
        for candidate_path in candidate_paths:
            card_suffix = candidate_path.lstrip("/")
            if normalized_no_leading.endswith(card_suffix):
                base_path = normalized_no_leading[: -len(card_suffix)].rstrip("/")
                agent_card_path = candidate_path
                break

        base_url = urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                f"/{base_path}" if base_path else "",
                "",
                "",
            )
        ).rstrip("/")
        return base_url, agent_card_path

    def _build_card_request_kwargs(self) -> dict[str, Any]:
        http_kwargs: dict[str, Any] = {"timeout": self._build_card_timeout()}
        if self._config.default_headers:
            http_kwargs["headers"] = {
                key: str(value)
                for key, value in self._config.default_headers.items()
                if value is not None
            }
        return http_kwargs

    async def _get_agent_card(self) -> AgentCard:
        if self._card is not None:
            return self._card

        if self._closed:
            raise A2AClientLifecycleError("client is closed")

        base_url, agent_card_path = self._resolve_agent_card_endpoint()
        resolver = self._card_resolver_factory(
            self._httpx_client,
            base_url,
            agent_card_path,
        )
        try:
            try:
                self._card = await resolver.get_agent_card(
                    http_kwargs=self._build_card_request_kwargs()
                )
            except TypeError:
                self._card = await resolver.get_agent_card()
        except Exception as exc:
            raise map_a2a_sdk_error(exc, operation="agent_card") from exc
        return self._card

    async def _get_client(self) -> Client:
        if self._closed:
            raise A2AClientLifecycleError("client is closed")
        async with self._lock:
            if self._sdk_client is not None:
                return self._sdk_client
            return await self._build_client()

    async def _build_client(self) -> Client:
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
        except TypeError:
            self._sdk_client = factory.create(card)
        if self._sdk_client is None:
            raise A2AClientError("Failed to initialize A2A client")
        return self._sdk_client

    async def _ensure_httpx_client(self) -> httpx.AsyncClient:
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=self._build_timeout())
            self._owns_http_client = True
        return self._httpx_client

    def _build_interceptors(self) -> list[ClientCallInterceptor]:
        return [_HeaderInterceptor(self._config.default_headers)]

    @classmethod
    def _extract_text_from_payload(cls, payload: Any) -> str | None:
        def extract_from_iterable(items: Any) -> str | None:
            if not isinstance(items, (list, tuple)):
                return None
            for item in items:
                extracted = cls._extract_text_from_payload(item)
                if extracted:
                    return extracted
            return None

        def extract_from_parts(parts: Any) -> str | None:
            if not isinstance(parts, (list, tuple)):
                return None
            collected: list[str] = []
            for part in parts:
                text_part = None
                if isinstance(part, TextPart):
                    text_part = part
                else:
                    root = getattr(part, "root", None)
                    if isinstance(root, TextPart):
                        text_part = root
                    elif isinstance(part, Mapping):
                        text_value = part.get("text")
                        if isinstance(text_value, str) and text_value.strip():
                            collected.append(text_value)
                            continue
                        mapped_root = part.get("root")
                        if isinstance(mapped_root, TextPart):
                            text_part = mapped_root
                        elif isinstance(part.get("role"), str):
                            nested = cls._extract_text_from_payload(part)
                            if nested:
                                collected.append(nested)
                                continue
                if text_part and getattr(text_part, "text", None):
                    collected.append(text_part.text)
            if collected:
                return "\n".join(collected)
            return None

        def extract_from_mapping(payload_map: Mapping[str, Any]) -> str | None:
            for key in (
                "content",
                "message",
                "messages",
                "result",
                "status",
                "text",
                "parts",
                "artifact",
                "artifacts",
                "history",
                "events",
                "root",
            ):
                if key not in payload_map:
                    continue
                value = payload_map[key]
                if value in (None, ""):
                    continue
                if key == "text" and isinstance(value, (str, int, float, bool)):
                    text_value = str(value).strip()
                    if text_value:
                        return text_value
                if key == "parts":
                    parts_text = extract_from_parts(value)
                    if parts_text:
                        return parts_text
                if key == "artifact":
                    artifact_text = cls._extract_text_from_payload(value)
                    if artifact_text:
                        return artifact_text
                if isinstance(value, (list, tuple)) and key in (
                    "messages",
                    "artifacts",
                    "history",
                    "events",
                ):
                    iterable_text = extract_from_iterable(value)
                    if iterable_text:
                        return iterable_text
                nested_text = cls._extract_text_from_payload(value)
                if nested_text:
                    return nested_text
            return None

        if isinstance(payload, (list, tuple)):
            return extract_from_iterable(payload)

        if isinstance(payload, Message):
            return extract_from_parts(payload.parts)

        if isinstance(payload, str):
            return payload.strip() or None

        status_payload = getattr(payload, "status", None)
        if status_payload is not None:
            text = cls._extract_text_from_payload(status_payload)
            if text:
                return text

        message_payload = getattr(payload, "message", None)
        if message_payload is not None:
            text = cls._extract_text_from_payload(message_payload)
            if text:
                return text

        artifact_payload = getattr(payload, "artifact", None)
        if artifact_payload is not None:
            text = cls._extract_text_from_payload(artifact_payload)
            if text:
                return text

        result_payload = getattr(payload, "result", None)
        if result_payload is not None:
            text = cls._extract_text_from_payload(result_payload)
            if text:
                return text

        history = getattr(payload, "history", None)
        if isinstance(history, (list, tuple)) and history:
            for item in reversed(history):
                text = cls._extract_text_from_payload(item)
                if text:
                    return text

        artifacts = getattr(payload, "artifacts", None)
        if isinstance(artifacts, (list, tuple)):
            for artifact in artifacts:
                artifact_parts = getattr(artifact, "parts", None)
                if isinstance(artifact_parts, (list, tuple)):
                    text = extract_from_parts(artifact_parts)
                    if text:
                        return text

        text = extract_from_parts(getattr(payload, "parts", None))
        if text:
            return text

        event_text = extract_from_iterable(getattr(payload, "events", None))
        if event_text:
            return event_text

        if isinstance(payload, Mapping):
            mapped_text = extract_from_mapping(payload)
            if mapped_text:
                return mapped_text

        mapping_payload = None
        if hasattr(payload, "model_dump") and callable(payload.model_dump):
            payload_dict = payload.model_dump()
            if isinstance(payload_dict, Mapping):
                mapping_payload = payload_dict
        elif hasattr(payload, "dict") and callable(payload.dict):
            payload_dict = payload.dict()
            if isinstance(payload_dict, Mapping):
                mapping_payload = payload_dict
        elif isinstance(getattr(payload, "__dict__", None), Mapping):
            mapping_payload = dict(payload.__dict__)

        if mapping_payload is not None:
            mapped_text = extract_from_mapping(mapping_payload)
            if mapped_text:
                return mapped_text

        return None

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

    def _split_request_metadata(
        self,
        metadata: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        request_metadata: dict[str, Any] = {}
        extra_headers: dict[str, str] = {}
        for key, value in dict(metadata or {}).items():
            if isinstance(key, str) and key.lower() == "authorization":
                if value is not None:
                    extra_headers["Authorization"] = str(value)
                continue
            request_metadata[key] = value
        return request_metadata or None, extra_headers or None

    def _build_call_context(
        self,
        extra_headers: Mapping[str, str] | None,
    ) -> ClientCallContext | None:
        if not extra_headers:
            return None
        return ClientCallContext(state={"headers": dict(extra_headers)})
