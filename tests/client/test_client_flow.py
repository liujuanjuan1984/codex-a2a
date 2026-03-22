from __future__ import annotations

import pytest
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    Message,
    Task,
    TaskIdParams,
    TaskQueryParams,
    TaskState,
    TaskStatus,
)
from codex_a2a.client import A2AClient, A2AClientConfig
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
