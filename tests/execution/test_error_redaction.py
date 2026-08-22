from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.events.event_queue import EventQueue

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
