from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.events.event_queue import EventQueue
from a2a.types import TaskState

from codex_a2a.execution.exec_runtime import CodexExecRuntime, ExecSessionHandle
from codex_a2a.execution.executor import CodexAgentExecutor
from codex_a2a.redact import REDACTED_PATH_PLACEHOLDER


@pytest.mark.asyncio
async def test_emit_error_redacts_absolute_paths() -> None:
    client = MagicMock()
    executor = CodexAgentExecutor(client, streaming_enabled=False)
    event_queue = AsyncMock(spec=EventQueue)

    await executor._emit_error(
        event_queue,
        task_id="task-1",
        context_id="context-1",
        message="Cannot open session file '/home/ubuntu/sessions/session-1.json': No such file",
        streaming_request=False,
    )

    task = event_queue.enqueue_event.call_args[0][0]
    text = task.status.message.parts[0].text
    assert REDACTED_PATH_PLACEHOLDER in text
    assert "/home/ubuntu/sessions/session-1.json" not in text


@pytest.mark.asyncio
async def test_emit_error_redacts_paths_in_streaming_task() -> None:
    client = MagicMock()
    executor = CodexAgentExecutor(client, streaming_enabled=True)
    event_queue = AsyncMock(spec=EventQueue)

    await executor._emit_error(
        event_queue,
        task_id="task-2",
        context_id="context-2",
        message="Timeout writing output to /var/log/codex/app.log",
        streaming_request=True,
    )

    task = event_queue.enqueue_event.call_args[0][0]
    text = task.status.message.parts[0].text
    assert REDACTED_PATH_PLACEHOLDER in text
    assert "/var/log/codex/app.log" not in text


@pytest.mark.asyncio
async def test_exec_session_failure_redacts_paths() -> None:
    client = MagicMock()

    async def empty_stream(*args, **kwargs):
        if False:
            yield {}

    client.stream_events.side_effect = lambda **kwargs: empty_stream()
    client.exec_start = AsyncMock(
        side_effect=FileNotFoundError(2, "No such file or directory", "/home/ubuntu/secret.txt")
    )

    runtime = CodexExecRuntime(client=client, request_handler=MagicMock())
    event_queue = AsyncMock(spec=EventQueue)
    handle = ExecSessionHandle(
        process_id="p-1",
        task_id="task-1",
        context_id="context-1",
        stop_event=asyncio.Event(),
        command_text="cat /home/ubuntu/secret.txt",
        owner_identity="alice",
    )

    await runtime._run_exec_session(
        handle=handle,
        request={"process_id": "p-1"},
        directory=None,
        event_queue=event_queue,
    )

    event = event_queue.enqueue_event.call_args[0][0]
    assert event.status.state == TaskState.TASK_STATE_FAILED
    text = event.status.message.parts[0].text
    assert REDACTED_PATH_PLACEHOLDER in text
    assert "/home/ubuntu/secret.txt" not in text
    error_metadata = event.metadata["codex"]["exec"]["error"]
    assert REDACTED_PATH_PLACEHOLDER in error_metadata
    assert "/home/ubuntu/secret.txt" not in error_metadata


@pytest.mark.asyncio
async def test_tool_call_error_redacts_paths() -> None:
    client = MagicMock()
    manager = MagicMock()
    manager.get_client = AsyncMock(
        side_effect=FileNotFoundError(2, "No such file or directory", "/home/ubuntu/tool.txt")
    )
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=False,
        a2a_client_manager=manager,
    )

    result = await executor._handle_a2a_call_tool(
        {
            "callID": "call-1",
            "tool": "a2a_call",
            "state": {
                "input": {
                    "url": "https://example.com/agent",
                    "message": "hello",
                }
            },
        }
    )

    assert REDACTED_PATH_PLACEHOLDER in result["error"]
    assert "/home/ubuntu/tool.txt" not in result["error"]
