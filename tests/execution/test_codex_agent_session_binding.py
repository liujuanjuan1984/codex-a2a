import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.types import (
    Artifact,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
)

from codex_a2a.a2a_proto import new_data_part, new_file_url_part, new_text_part, part_text
from codex_a2a.client import A2AClient
from codex_a2a.execution.executor import CodexAgentExecutor
from codex_a2a.upstream.client import CodexMessage
from tests.support.context import DummyEventQueue, make_request_context
from tests.support.dummy_clients import DummyChatCodexClient


def _terminal_task(queue: DummyEventQueue) -> Task:
    return [
        event
        for event in queue.events
        if isinstance(event, Task)
        and event.status.state
        in {
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_REJECTED,
        }
    ][-1]


@pytest.mark.asyncio
async def test_agent_prefers_metadata_shared_session_id() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    ctx = make_request_context(
        task_id="t-1",
        context_id="c-1",
        text="hello",
        metadata={"shared": {"session": {"id": "ses-bound"}}},
    )
    await executor.execute(ctx, q)

    assert client.created_sessions == 0
    assert client.sent_session_ids == ["ses-bound"]


@pytest.mark.asyncio
async def test_agent_maps_rich_input_parts_to_structured_codex_input() -> None:
    class RichInputClient(DummyChatCodexClient):
        async def create_session(
            self,
            title: str | None = None,
            *,
            directory: str | None = None,
            execution_options=None,  # noqa: ANN001
        ) -> str:
            del execution_options
            self.created_sessions += 1
            self.sent_inputs.append({"created_session_title": title, "directory": directory})
            return f"ses-created-{self.created_sessions}"

    client = RichInputClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    ctx = make_request_context(
        task_id="t-rich",
        context_id="c-rich",
        text="",
        parts=[
            new_file_url_part(
                "https://example.com/screenshot.png",
                media_type="image/png",
                filename="screenshot.png",
            ),
            new_data_part(
                {
                    "type": "mention",
                    "name": "Demo App",
                    "path": "app://demo-app",
                }
            ),
        ],
    )
    await executor.execute(ctx, q)

    assert client.created_sessions == 1
    assert client.sent_session_ids == ["ses-created-1"]
    assert client.sent_inputs[0]["created_session_title"] == "Demo App"
    assert client.sent_inputs[1]["input_items"] == [
        {"type": "image", "url": "https://example.com/screenshot.png"},
        {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
    ]


@pytest.mark.asyncio
async def test_agent_forwards_request_execution_options_from_metadata() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    ctx = make_request_context(
        task_id="t-exec",
        context_id="c-exec",
        text="hello",
        metadata={
            "codex": {
                "execution": {
                    "model": "gpt-5.2-codex",
                    "effort": "high",
                    "summary": "concise",
                    "personality": "pragmatic",
                }
            }
        },
    )
    await executor.execute(ctx, q)

    execution_options = client.sent_inputs[0]["execution_options"]
    assert execution_options is not None
    assert execution_options.model == "gpt-5.2-codex"
    assert execution_options.effort == "high"
    assert execution_options.summary == "concise"
    assert execution_options.personality == "pragmatic"


@pytest.mark.asyncio
async def test_agent_rejects_invalid_request_execution_options_metadata() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    ctx = make_request_context(
        task_id="t-exec-invalid",
        context_id="c-exec-invalid",
        text="hello",
        metadata={"codex": {"execution": {"effort": "turbo"}}},
    )
    await executor.execute(ctx, q)

    task = _terminal_task(q)
    assert task.status.state == TaskState.TASK_STATE_FAILED
    assert task.status.message is not None
    assert (
        part_text(task.status.message.parts[0])
        == "metadata.codex.execution.effort must be one of: high, low, medium, minimal, none, xhigh"
    )


@pytest.mark.asyncio
async def test_agent_rejects_non_image_file_parts() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    ctx = make_request_context(
        task_id="t-bad-file",
        context_id="c-bad-file",
        text="",
        parts=[
            new_file_url_part(
                "https://example.com/report.pdf",
                media_type="application/pdf",
                filename="report.pdf",
            )
        ],
    )
    await executor.execute(ctx, q)

    task = _terminal_task(q)
    assert task.status.state == TaskState.TASK_STATE_FAILED
    assert task.status.message is not None
    assert (
        part_text(task.status.message.parts[0])
        == "Only text, image file, and codex rich input data parts are supported."
    )


@pytest.mark.asyncio
async def test_agent_caches_bound_session_id_for_followup_requests() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        session_cache_ttl_seconds=3600,
        session_cache_maxsize=100,
    )
    q = DummyEventQueue()

    ctx1 = make_request_context(
        task_id="t-1",
        context_id="c-1",
        text="hello",
        metadata={"shared": {"session": {"id": "ses-bound"}}},
    )
    await executor.execute(ctx1, q)

    ctx2 = make_request_context(
        task_id="t-2",
        context_id="c-1",
        text="follow",
        metadata=None,
    )
    await executor.execute(ctx2, q)

    assert client.created_sessions == 0
    assert client.sent_session_ids == ["ses-bound", "ses-bound"]


@pytest.mark.asyncio
async def test_agent_dedupes_concurrent_session_creates_per_context() -> None:
    class SlowCreateClient(DummyChatCodexClient):
        async def create_session(
            self,
            title: str | None = None,
            *,
            directory: str | None = None,
            execution_options=None,  # noqa: ANN001
        ) -> str:
            await asyncio.sleep(0.05)
            return await super().create_session(
                title=title,
                directory=directory,
                execution_options=execution_options,
            )

    client = SlowCreateClient()
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        session_cache_ttl_seconds=3600,
        session_cache_maxsize=100,
    )

    async def run_one(task_id: str) -> None:
        q = DummyEventQueue()
        ctx = make_request_context(task_id=task_id, context_id="c-1", text="hi", metadata=None)
        await executor.execute(ctx, q)

    await asyncio.gather(run_one("t-1"), run_one("t-2"), run_one("t-3"))

    assert client.created_sessions == 1


@pytest.mark.asyncio
async def test_agent_uses_stable_fallback_message_id_when_upstream_missing_message_id() -> None:
    class MissingMessageIdClient(DummyChatCodexClient):
        async def send_message(
            self,
            session_id: str,
            text: str,
            *,
            directory: str | None = None,
            execution_options=None,  # noqa: ANN001
            timeout_override=None,  # noqa: ANN001
        ) -> CodexMessage:
            del text, directory, execution_options, timeout_override
            self.sent_session_ids.append(session_id)
            return CodexMessage(
                text="echo:hello",
                session_id=session_id,
                message_id=None,
                raw={},
            )

    client = MissingMessageIdClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    await executor.execute(
        make_request_context(task_id="t-fallback", context_id="c-fallback", text="hello"),
        q,
    )

    task = _terminal_task(q)
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert task.metadata is not None
    assert task.status.message is not None
    assert "message_id" not in task.metadata["shared"]["session"]
    assert task.status.message.message_id == "t-fallback:c-fallback:assistant"


@pytest.mark.asyncio
async def test_agent_includes_usage_in_non_stream_task_metadata() -> None:
    class UsageClient(DummyChatCodexClient):
        async def send_message(
            self,
            session_id: str,
            text: str,
            *,
            directory: str | None = None,
            execution_options=None,  # noqa: ANN001
            timeout_override=None,  # noqa: ANN001
        ) -> CodexMessage:
            del text, directory, execution_options, timeout_override
            self.sent_session_ids.append(session_id)
            return CodexMessage(
                text="echo:hello",
                session_id=session_id,
                message_id="msg-usage",
                raw={
                    "info": {
                        "tokens": {
                            "input": 7,
                            "output": 3,
                            "reasoning": 0,
                            "cache": {"read": 0, "write": 0},
                        },
                        "cost": 0.0007,
                    }
                },
            )

    client = UsageClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    q = DummyEventQueue()

    await executor.execute(
        make_request_context(task_id="t-usage", context_id="c-usage", text="hello"),
        q,
    )

    task = _terminal_task(q)
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert task.metadata is not None
    usage = task.metadata["shared"]["usage"]
    assert usage["input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_agent_handles_a2a_call_tool() -> None:
    class _MockA2AClient:
        extract_text = staticmethod(A2AClient.extract_text)

        async def send_message(self, text: str, **_kwargs):
            yield StreamResponse(
                artifact_update=TaskArtifactUpdateEvent(
                    task_id="remote-task",
                    context_id="remote-ctx",
                    artifact=Artifact(
                        artifact_id="a1",
                        name="response",
                        parts=[new_text_part(f"remote response to {text}")],
                    ),
                )
            )

        async def close(self) -> None:
            pass

    class _MockManager:
        async def get_client(self, _agent_url: str) -> _MockA2AClient:
            return _MockA2AClient()

    raw_response = {
        "parts": [
            {
                "type": "tool",
                "tool": "a2a_call",
                "callID": "call-1",
                "state": {
                    "status": "calling",
                    "input": {"url": "http://remote", "message": "hello remote"},
                },
            }
        ]
    }

    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        a2a_client_manager=_MockManager(),
    )
    result = await executor._maybe_handle_tools(raw_response)

    assert result is not None
    assert len(result) == 1
    assert result[0]["call_id"] == "call-1"
    assert "remote response to hello remote" in result[0]["output"]


@pytest.mark.asyncio
async def test_agent_supports_tool_loop_and_merges_stream_output() -> None:
    class ToolLoopClient(DummyChatCodexClient):
        def __init__(self) -> None:
            super().__init__()
            self.call_count = 0

        async def send_message(self, *args, **kwargs) -> CodexMessage:
            del args, kwargs
            self.call_count += 1
            if self.call_count == 1:
                return CodexMessage(
                    text="call tool",
                    session_id="session",
                    message_id="m-1",
                    raw={
                        "parts": [
                            {
                                "type": "tool",
                                "tool": "a2a_call",
                                "callID": "tool-1",
                                "state": {
                                    "status": "calling",
                                    "input": {"url": "http://tool", "message": "payload"},
                                },
                            }
                        ]
                    },
                )
            return CodexMessage(
                text="done",
                session_id="session",
                message_id="m-2",
                raw={},
            )

    class _MockManager:
        async def get_client(self, _agent_url: str):
            async def _send_message(_text: str, **_kwargs):
                yield StreamResponse(
                    task=Task(
                        id="remote-task",
                        context_id="remote-ctx",
                        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
                    )
                )
                yield StreamResponse(
                    artifact_update=TaskArtifactUpdateEvent(
                        task_id="remote-task",
                        context_id="remote-ctx",
                        artifact=Artifact(
                            artifact_id="a1",
                            name="response",
                            parts=[new_text_part("streamed tool output")],
                        ),
                    ),
                )

            return MagicMock(
                send_message=_send_message,
                extract_text=A2AClient.extract_text,
                close=AsyncMock(),
            )

    client = ToolLoopClient()
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        a2a_client_manager=_MockManager(),
    )
    queue = DummyEventQueue()

    await executor.execute(
        make_request_context(task_id="t1", context_id="c1", text="start"),
        queue,
    )

    assert client.call_count == 2
    task = _terminal_task(queue)
    assert task.status.message is not None
    assert part_text(task.status.message.parts[0]) == "done"


def test_executor_merge_streamed_a2a_tool_output() -> None:
    assert CodexAgentExecutor._merge_streamed_tool_output("hello", "hello world") == "hello world"
    assert (
        CodexAgentExecutor._merge_streamed_tool_output("hello world", "from peer")
        == "hello world\nfrom peer"
    )
    assert CodexAgentExecutor._merge_streamed_tool_output("hello world", "world") == "hello world"


@pytest.mark.asyncio
async def test_agent_handles_a2a_call_tool_input_validation_errors() -> None:
    client = DummyChatCodexClient()
    executor = CodexAgentExecutor(client, streaming_enabled=False)

    raw_response = {
        "parts": [
            {
                "type": "tool",
                "tool": "a2a_call",
                "callID": "c1",
                "state": {"status": "calling", "input": {"url": "h", "message": "m"}},
            }
        ]
    }
    result = await executor._maybe_handle_tools(raw_response)
    assert result is not None
    assert result[0]["error"] == "A2A client manager is not available"

    class _MockManager:
        async def get_client(self, _agent_url: str):
            return MagicMock()

    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        a2a_client_manager=_MockManager(),
    )
    raw_response["parts"][0]["state"]["input"] = "invalid"
    result = await executor._maybe_handle_tools(raw_response)
    assert result is not None
    assert result[0]["error"] == "Invalid input format"

    raw_response["parts"][0]["state"]["input"] = {"url": "http://x"}
    result = await executor._maybe_handle_tools(raw_response)
    assert result is not None
    assert result[0]["error"] == "Missing url or message"
