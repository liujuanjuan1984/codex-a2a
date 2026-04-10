from __future__ import annotations

from typing import Any

import pytest
from a2a.client.auth.interceptor import AuthInterceptor
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Artifact,
    HTTPAuthSecurityScheme,
    Message,
    Part,
    Role,
    SecurityScheme,
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
    A2AUnsupportedBindingError,
    StaticCredentialService,
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


class _MockSDKClient:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []
        self.get_task_calls: list[TaskQueryParams] = []
        self.get_task_contexts: list[Any] = []
        self.cancel_calls: list[TaskIdParams] = []
        self.cancel_contexts: list[Any] = []

    async def send_message(
        self,
        request: Message,
        *,
        configuration=None,
        context=None,
        request_metadata=None,
        extensions=None,
    ):
        self.send_calls.append(
            {
                "request": request,
                "configuration": configuration,
                "context": context,
                "request_metadata": request_metadata,
                "extensions": extensions,
            }
        )
        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.working),
        )
        yield task

    async def get_task(self, request: TaskQueryParams, *, context=None, extensions=None) -> Task:
        self.get_task_calls.append(request)
        self.get_task_contexts.append(context)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.completed),
        )

    async def cancel_task(self, request: TaskIdParams, *, context=None, extensions=None) -> Task:
        self.cancel_calls.append(request)
        self.cancel_contexts.append(context)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.canceled),
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_send_get_task_and_cancel_use_sdk_methods() -> None:
    sdk_client = _MockSDKClient()
    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )
    client._sdk_client = sdk_client  # noqa: SLF001

    send_result = await client.send(
        A2ASendRequest(
            text="hello",
            metadata={"authorization": "Bearer token", "trace_id": "trace-1"},
            accepted_output_modes=["text/plain"],
            history_length=3,
            blocking=False,
        )
    )
    assert send_result.id == "task-1"
    send_call = sdk_client.send_calls[0]
    assert send_call["request_metadata"] == {"trace_id": "trace-1"}
    assert send_call["context"].state["headers"] == {"Authorization": "Bearer token"}
    assert send_call["configuration"].accepted_output_modes == ["text/plain"]
    assert send_call["configuration"].history_length == 3
    assert send_call["configuration"].blocking is False

    task_result = await client.get_task(
        A2AGetTaskRequest(
            task_id="task-1",
            history_length=2,
            metadata={"authorization": "Bearer token", "trace_id": "trace-2"},
        )
    )
    assert task_result.id == "task-1"
    assert sdk_client.get_task_calls[0].model_dump(by_alias=False) == {
        "id": "task-1",
        "history_length": 2,
        "metadata": {"trace_id": "trace-2"},
    }
    assert sdk_client.get_task_contexts[0].state["headers"] == {"Authorization": "Bearer token"}

    cancel_result = await client.cancel(
        A2ACancelTaskRequest(
            task_id="task-1",
            metadata={"authorization": "Bearer token", "trace_id": "trace-3"},
        )
    )
    assert cancel_result.status.state == TaskState.canceled
    assert sdk_client.cancel_calls[0].model_dump(by_alias=False) == {
        "id": "task-1",
        "metadata": {"trace_id": "trace-3"},
    }
    assert sdk_client.cancel_contexts[0].state["headers"] == {"Authorization": "Bearer token"}


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


def test_build_interceptors_adds_sdk_auth_interceptor_for_config_credentials() -> None:
    client = A2AClient(
        A2AClientConfig(
            agent_url="https://example.org",
            auth_credentials={"bearerAuth": "peer-token"},
        ),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )

    interceptors = client._build_interceptors()  # noqa: SLF001

    assert any(isinstance(interceptor, AuthInterceptor) for interceptor in interceptors)


@pytest.mark.asyncio
async def test_static_credential_service_works_with_sdk_auth_interceptor() -> None:
    card = AgentCard(
        name="mock",
        description="mock agent",
        url="https://example.org",
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
        security_schemes={
            "bearerAuth": SecurityScheme(
                root=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    bearer_format="opaque",
                )
            )
        },
        security=[{"bearerAuth": []}],
    )
    interceptor = AuthInterceptor(StaticCredentialService({"bearerAuth": "peer-token"}))

    _payload, http_kwargs = await interceptor.intercept(
        "message/send",
        {},
        {},
        card,
        None,
    )

    assert http_kwargs["headers"]["Authorization"] == "Bearer peer-token"


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
