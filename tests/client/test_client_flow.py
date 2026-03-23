from __future__ import annotations

import httpx
import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskQueryParams,
    TaskState,
    TaskStatus,
    TextPart,
)

from codex_a2a.client import (
    A2AClient,
    A2AClientConfig,
    A2AClientConfigError,
    A2AUnsupportedBindingError,
)
from codex_a2a.client.types import A2ACancelTaskRequest, A2AGetTaskRequest, A2ASendRequest


class _MockAsyncHttpClient:
    def __init__(self) -> None:
        pass

    async def aclose(self) -> None:
        return None


class _MockAgentCardResolver:
    calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def get_agent_card(self, *_, **__) -> AgentCard:
        _MockAgentCardResolver.calls += 1
        return AgentCard(
            name="mock",
            description="mock agent",
            url="https://example.org",
            version="1.0.0",
            capabilities=AgentCapabilities(),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=[],
        )


class _MockAgentCardResolverWithTimeout:
    def __init__(self, *_args, **_kwargs) -> None:
        self.http_kwargs = {}

    async def get_agent_card(self, http_kwargs=None, **_kwargs) -> AgentCard:
        if http_kwargs is not None:
            self.http_kwargs = dict(http_kwargs)
        return AgentCard(
            name="mock",
            description="mock agent",
            url="https://example.org",
            version="1.0.0",
            capabilities=AgentCapabilities(),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=[],
        )


class _CapturingAgentCardResolver:
    last_base_url: str | None = None
    last_agent_card_path: str | None = None

    def __init__(self, _httpx_client, base_url: str, agent_card_path: str) -> None:
        _CapturingAgentCardResolver.last_base_url = base_url
        _CapturingAgentCardResolver.last_agent_card_path = agent_card_path

    async def get_agent_card(self, *_, **__) -> AgentCard:
        return AgentCard(
            name="mock",
            description="mock agent",
            url="https://example.org",
            version="1.0.0",
            capabilities=AgentCapabilities(),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=[],
        )


class _MockSDKClient:
    def __init__(self) -> None:
        self.send_calls = 0
        self.get_task_calls: list[TaskQueryParams] = []
        self.cancel_calls: list[TaskIdParams] = []

    async def send_message(
        self,
        _request: Message,
        *,
        configuration=None,
        context=None,
        request_metadata=None,
        extensions=None,
    ):
        self.send_calls += 1
        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.working),
        )
        yield task

    async def get_task(self, request: TaskQueryParams, *_, **__) -> Task:
        self.get_task_calls.append(request)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.completed),
        )

    async def cancel_task(self, request: TaskIdParams, *_, **__) -> Task:
        self.cancel_calls.append(request)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.canceled),
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_send_get_task_and_cancel_use_sdk_methods() -> None:
    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )
    client._sdk_client = _MockSDKClient()  # noqa: SLF001

    send_result = await client.send(A2ASendRequest(text="hello"))
    assert send_result.id == "task-1"

    task_result = await client.get_task(A2AGetTaskRequest(task_id="task-1"))
    assert task_result.id == "task-1"

    cancel_result = await client.cancel(A2ACancelTaskRequest(task_id="task-1"))
    assert cancel_result.status.state == TaskState.canceled


@pytest.mark.asyncio
async def test_get_agent_card_uses_resolver_and_cached() -> None:
    _MockAgentCardResolver.calls = 0
    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )

    card = await client.get_agent_card()
    card_second = await client.get_agent_card()

    assert card.url == "https://example.org"
    assert card_second.url == "https://example.org"
    assert _MockAgentCardResolver.calls == 1


@pytest.mark.asyncio
async def test_get_agent_card_passes_card_fetch_timeout_to_resolver() -> None:
    resolver = _MockAgentCardResolverWithTimeout()

    class _Factory:
        last_instance: _MockAgentCardResolverWithTimeout | None = None

        def __call__(self, *_args, **_kwargs) -> _MockAgentCardResolverWithTimeout:
            _Factory.last_instance = resolver
            return resolver

    client = A2AClient(
        A2AClientConfig(
            agent_url="https://example.org",
            card_fetch_timeout_seconds=7.5,
            default_headers={"Authorization": "Bearer peer-token"},
        ),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_Factory(),
    )
    try:
        await client.get_agent_card()
    finally:
        await client.close()

    assert _Factory.last_instance is resolver
    timeout = resolver.http_kwargs.get("timeout")
    assert timeout is not None
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 7.5
    assert resolver.http_kwargs["headers"] == {"Authorization": "Bearer peer-token"}


@pytest.mark.asyncio
async def test_get_agent_card_normalizes_explicit_well_known_path() -> None:
    _CapturingAgentCardResolver.last_base_url = None
    _CapturingAgentCardResolver.last_agent_card_path = None
    client = A2AClient(
        A2AClientConfig(agent_url="https://ops.example.com/tenant/.well-known/agent-card.json"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_CapturingAgentCardResolver,
    )

    card = await client.get_agent_card()

    assert card.url == "https://example.org"
    assert _CapturingAgentCardResolver.last_base_url == "https://ops.example.com/tenant"
    assert _CapturingAgentCardResolver.last_agent_card_path == "/.well-known/agent-card.json"


@pytest.mark.asyncio
async def test_get_agent_card_rejects_relative_agent_url() -> None:
    client = A2AClient(
        A2AClientConfig(agent_url="/relative/path"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )

    with pytest.raises(A2AClientConfigError, match="absolute URL"):
        await client.get_agent_card()


@pytest.mark.asyncio
async def test_build_client_maps_unsupported_transport_binding() -> None:
    class _RejectingFactory:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def create(self, *_args, **_kwargs):
            raise ValueError("No shared transport found")

    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
        client_factory_type=_RejectingFactory,
    )

    with pytest.raises(A2AUnsupportedBindingError):
        await client._build_client()


def test_extract_text_prefers_stream_artifact_payload() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(state=TaskState.working),
    )
    update = TaskArtifactUpdateEvent(
        task_id="remote-task",
        context_id="remote-context",
        artifact=Artifact(
            artifact_id="artifact-1",
            name="response",
            parts=[Part(root=TextPart(text="streamed remote text"))],
        ),
    )

    assert A2AClient.extract_text((task, update)) == "streamed remote text"


def test_extract_text_reads_task_status_message() -> None:
    task = Task(
        id="remote-task",
        context_id="remote-context",
        status=TaskStatus(
            state=TaskState.completed,
            message=Message(
                role=Role.agent,
                message_id="m1",
                parts=[Part(root=TextPart(text="status message text"))],
            ),
        ),
    )

    assert A2AClient.extract_text(task) == "status message text"


def test_extract_text_reads_nested_mapping_payload() -> None:
    payload = {
        "result": {
            "history": [
                {"parts": [{"text": "mapped nested text"}]},
            ]
        }
    }

    assert A2AClient.extract_text(payload) == "mapped nested text"


def test_extract_text_reads_model_dump_payload() -> None:
    class _Payload:
        def model_dump(self) -> dict[str, object]:
            return {"artifacts": [{"parts": [{"text": "model dump text"}]}]}

    assert A2AClient.extract_text(_Payload()) == "model dump text"
