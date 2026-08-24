from __future__ import annotations

import json
from base64 import b64encode

import httpx
import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
)
from google.protobuf.json_format import MessageToDict

from codex_a2a.client import A2AClient, A2AClientConfig

_PEER_URL = "https://peer.example.com"
_EXTENSION_URI = "https://example.com/extensions/test"


def _agent_card() -> AgentCard:
    return AgentCard(
        name="HTTP stub peer",
        description="Exercises the real SDK JSON-RPC transport.",
        version="1.0",
        supported_interfaces=[
            AgentInterface(
                url=f"{_PEER_URL}/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )


def _http_stub(requests: dict[str, httpx.Request]) -> httpx.MockTransport:
    card = _agent_card()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            requests["GetAgentCard"] = request
            return httpx.Response(200, json=MessageToDict(card))

        payload = json.loads(request.content)
        method = payload["method"]
        requests[method] = request
        if method == "SendMessage":
            result = MessageToDict(
                SendMessageResponse(
                    message=Message(
                        message_id="reply-1",
                        role=Role.ROLE_AGENT,
                        parts=[Part(text="ok")],
                    )
                )
            )
        elif method in {"GetTask", "CancelTask"}:
            state = (
                TaskState.TASK_STATE_COMPLETED
                if method == "GetTask"
                else TaskState.TASK_STATE_CANCELED
            )
            result = MessageToDict(
                Task(
                    id="task-1",
                    context_id="context-1",
                    status=TaskStatus(state=state),
                )
            )
        else:  # pragma: no cover - keeps unexpected SDK calls visible
            raise AssertionError(f"Unexpected JSON-RPC method: {method}")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": result},
        )

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "expected_authorization"),
    [
        ("Bearer peer-token", "Bearer peer-token"),
        (f"Basic {b64encode(b'user:pass').decode()}", "Basic dXNlcjpwYXNz"),
    ],
    ids=("bearer", "basic"),
)
async def test_sdk_jsonrpc_requests_send_configured_headers(
    authorization: str,
    expected_authorization: str,
) -> None:
    requests: dict[str, httpx.Request] = {}
    config = A2AClientConfig(
        agent_url=_PEER_URL,
        default_headers={"Authorization": authorization},
        extensions=[_EXTENSION_URI],
    )
    async with httpx.AsyncClient(transport=_http_stub(requests)) as http_client:
        client = A2AClient(config, httpx_client=http_client)

        await client.send(
            SendMessageRequest(
                message=Message(
                    message_id="message-1",
                    role=Role.ROLE_USER,
                    parts=[Part(text="hello")],
                )
            )
        )
        await client.get_task(GetTaskRequest(id="task-1"))
        await client.cancel(CancelTaskRequest(id="task-1"))

    for method in ("GetAgentCard", "SendMessage", "GetTask", "CancelTask"):
        assert requests[method].headers["Authorization"] == expected_authorization
        assert requests[method].headers["A2A-Version"] == "1.0"
    for method in ("SendMessage", "GetTask", "CancelTask"):
        assert requests[method].headers["A2A-Extensions"] == _EXTENSION_URI


@pytest.mark.asyncio
async def test_sdk_jsonrpc_request_preserves_explicit_authorization_override() -> None:
    requests: dict[str, httpx.Request] = {}
    config = A2AClientConfig(
        agent_url=_PEER_URL,
        default_headers={"Authorization": "Bearer default-token"},
    )
    async with httpx.AsyncClient(transport=_http_stub(requests)) as http_client:
        client = A2AClient(config, httpx_client=http_client)

        await client.send(
            SendMessageRequest(
                message=Message(
                    message_id="message-1",
                    role=Role.ROLE_USER,
                    parts=[Part(text="hello")],
                ),
                metadata={"authorization": "Bearer explicit-token"},
            )
        )

    assert requests["GetAgentCard"].headers["Authorization"] == "Bearer default-token"
    assert requests["SendMessage"].headers["Authorization"] == "Bearer explicit-token"
