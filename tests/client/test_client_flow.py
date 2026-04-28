from __future__ import annotations

from typing import Any

import pytest
from a2a.client import ClientCallContext
from a2a.client.auth.interceptor import AuthInterceptor
from a2a.client.interceptors import BeforeArgs
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Artifact,
    CancelTaskRequest,
    GetTaskRequest,
    HTTPAuthSecurityScheme,
    Message,
    Role,
    SecurityRequirement,
    SecurityScheme,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
)
from a2a.utils.constants import TransportProtocol

from codex_a2a.a2a_proto import new_data_part, new_text_part, proto_to_python
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
            version="1.0.0",
            capabilities=AgentCapabilities(),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=[],
            supported_interfaces=[
                AgentInterface(
                    url="https://example.org",
                    protocol_binding=TransportProtocol.HTTP_JSON,
                    protocol_version="1.0",
                )
            ],
        )


class _MockSDKClient:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []
        self.get_task_calls: list[GetTaskRequest] = []
        self.get_task_contexts: list[Any] = []
        self.cancel_calls: list[CancelTaskRequest] = []
        self.cancel_contexts: list[Any] = []

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context=None,
    ):
        self.send_calls.append(
            {
                "request": request,
                "context": context,
            }
        )
        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
        yield StreamResponse(task=task)

    async def get_task(self, request: GetTaskRequest, *, context=None) -> Task:
        self.get_task_calls.append(request)
        self.get_task_contexts.append(context)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        )

    async def cancel_task(self, request: CancelTaskRequest, *, context=None) -> Task:
        self.cancel_calls.append(request)
        self.cancel_contexts.append(context)
        return Task(
            id=request.id,
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
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
    assert send_result.HasField("task")
    assert send_result.task.id == "task-1"
    send_call = sdk_client.send_calls[0]
    assert proto_to_python(send_call["request"].metadata) == {"trace_id": "trace-1"}
    assert send_call["context"].service_parameters == {"Authorization": "Bearer token"}
    assert send_call["request"].configuration.accepted_output_modes == ["text/plain"]
    assert send_call["request"].configuration.history_length == 3
    assert send_call["request"].configuration.return_immediately is True

    task_result = await client.get_task(
        A2AGetTaskRequest(
            task_id="task-1",
            history_length=2,
            metadata={"authorization": "Bearer token", "trace_id": "trace-2"},
        )
    )
    assert task_result.id == "task-1"
    assert proto_to_python(sdk_client.get_task_calls[0]) == {
        "id": "task-1",
        "history_length": 2,
    }
    assert sdk_client.get_task_contexts[0].service_parameters == {"Authorization": "Bearer token"}

    cancel_result = await client.cancel(
        A2ACancelTaskRequest(
            task_id="task-1",
            metadata={"authorization": "Bearer token", "trace_id": "trace-3"},
        )
    )
    assert cancel_result.status.state == TaskState.TASK_STATE_CANCELED
    assert proto_to_python(sdk_client.cancel_calls[0]) == {
        "id": "task-1",
        "metadata": {"trace_id": "trace-3"},
    }
    assert sdk_client.cancel_contexts[0].service_parameters == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_send_supports_v1_parts_and_message_payloads() -> None:
    sdk_client = _MockSDKClient()
    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
    )
    client._sdk_client = sdk_client  # noqa: SLF001

    await client.send(
        A2ASendRequest(
            parts=[
                new_text_part("hello"),
                new_data_part({"kind": "mention", "path": "/tmp/skill"}),
            ],
            message_id="msg-parts",
            context_id="ctx-parts",
        )
    )
    parts_request = sdk_client.send_calls[0]["request"]
    assert parts_request.message.message_id == "msg-parts"
    assert parts_request.message.context_id == "ctx-parts"
    assert proto_to_python(parts_request.message.parts[1].data) == {
        "kind": "mention",
        "path": "/tmp/skill",
    }

    outbound_message = Message(
        message_id="msg-raw",
        role=Role.ROLE_USER,
        parts=[new_text_part("direct message")],
    )
    await client.send(A2ASendRequest(message=outbound_message))
    message_request = sdk_client.send_calls[1]["request"]
    assert message_request.message.message_id == "msg-raw"
    assert message_request.message.parts[0].text == "direct message"


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

    assert card.supported_interfaces[0].url == "https://example.org"
    assert card_second.supported_interfaces[0].url == "https://example.org"
    assert _MockAgentCardResolver.calls == 1


@pytest.mark.asyncio
async def test_build_client_uses_sdk_url_creation_with_normalized_card_path() -> None:
    observed: dict[str, Any] = {}

    async def _capturing_creator(agent, **kwargs):
        observed["agent"] = agent
        observed["kwargs"] = kwargs
        return _MockSDKClient()

    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org/tenant/.well-known/agent-card.json"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
        client_creator=_capturing_creator,
    )

    await client._build_client()

    assert observed["agent"] == "https://example.org/tenant"
    assert observed["kwargs"]["relative_card_path"] == "/.well-known/agent-card.json"
    assert observed["kwargs"]["resolver_http_kwargs"]["timeout"].connect == 5.0


@pytest.mark.asyncio
async def test_build_client_maps_unsupported_transport_binding() -> None:
    async def _rejecting_creator(*_args, **_kwargs):
        raise ValueError("No shared transport found")

    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=_MockAsyncHttpClient(),
        card_resolver_factory=_MockAgentCardResolver,
        client_creator=_rejecting_creator,
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
    security_requirement = SecurityRequirement()
    security_requirement.schemes["bearerAuth"].list.extend([])
    card = AgentCard(
        name="mock",
        description="mock agent",
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
        supported_interfaces=[
            AgentInterface(
                url="https://example.org",
                protocol_binding=TransportProtocol.HTTP_JSON,
                protocol_version="1.0",
            )
        ],
        security_schemes={
            "bearerAuth": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    bearer_format="opaque",
                )
            )
        },
        security_requirements=[security_requirement],
    )
    interceptor = AuthInterceptor(StaticCredentialService({"bearerAuth": "peer-token"}))

    before_args = BeforeArgs(
        input={},
        method="message/send",
        agent_card=card,
        context=ClientCallContext(service_parameters={}),
    )
    await interceptor.before(before_args)

    assert before_args.context is not None
    assert before_args.context.service_parameters["Authorization"] == "Bearer peer-token"
    assert before_args.input == {}


def test_extract_text_prefers_stream_artifact_payload() -> None:
    update = TaskArtifactUpdateEvent(
        task_id="remote-task",
        context_id="remote-context",
        artifact=Artifact(
            artifact_id="artifact-1",
            name="response",
            parts=[new_text_part("streamed remote text")],
        ),
    )

    assert A2AClient.extract_text(StreamResponse(artifact_update=update)) == "streamed remote text"


def test_extract_text_reads_stream_message_payload() -> None:
    payload = StreamResponse(
        message=Message(
            role=Role.ROLE_AGENT,
            message_id="m2",
            parts=[new_text_part("stream message text")],
        )
    )

    assert A2AClient.extract_text(payload) == "stream message text"
