import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types import TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from codex_a2a.execution.discovery_runtime import CodexDiscoveryRuntime
from codex_a2a.execution.exec_runtime import CodexExecRuntime, ExecSessionHandle
from tests.support.context import DummyEventQueue


def _artifact_updates(queue: DummyEventQueue) -> list[TaskArtifactUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskArtifactUpdateEvent)]


def _status_updates(queue: DummyEventQueue) -> list[TaskStatusUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]


def _part_text(event: TaskArtifactUpdateEvent) -> str:
    part = event.artifact.parts[0]
    return getattr(part, "text", None) or getattr(getattr(part, "root", None), "text", "") or ""


def _part_data(event: TaskArtifactUpdateEvent) -> dict[str, Any]:
    part = event.artifact.parts[0]
    data = getattr(part, "data", None) or getattr(getattr(part, "root", None), "data", None)
    return data if isinstance(data, dict) else {}


class RecordingRequestHandler:
    def __init__(self, *, hold_open: bool = False) -> None:
        self.saved_task = None
        self.saved_context = None
        self.saved_producer = None
        self._hold_open = hold_open
        self._stop_event = asyncio.Event()
        self.created_tasks: list[asyncio.Task[None]] = []

    async def start_background_task_stream(self, *, task, context=None, producer=None):  # noqa: ANN001
        self.saved_task = task
        self.saved_context = context
        self.saved_producer = producer
        if self._hold_open:
            created_task = asyncio.create_task(self._stop_event.wait())
        else:
            created_task = asyncio.create_task(asyncio.sleep(0))
        self.created_tasks.append(created_task)
        return created_task

    async def close(self) -> None:
        self._stop_event.set()
        for created_task in self.created_tasks:
            created_task.cancel()
        for created_task in self.created_tasks:
            with pytest.raises(asyncio.CancelledError):
                await created_task


class DiscoveryClientStub:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def stream_events(  # noqa: ANN201
        self,
        stop_event=None,  # noqa: ANN001
        *,
        directory: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        del directory
        for event in self._events:
            if stop_event is not None and stop_event.is_set():
                break
            yield event


class ExecClientStub:
    def __init__(
        self,
        *,
        stream_events: list[dict[str, Any]],
        exec_result: dict[str, Any] | None = None,
        exec_error: Exception | None = None,
        exec_start_delay: float = 0.0,
    ) -> None:
        self._stream_events = stream_events
        self._exec_result = exec_result or {"stdout": "", "stderr": "", "exitCode": 0}
        self._exec_error = exec_error
        self._exec_start_delay = exec_start_delay
        self.stream_timeout = 12.0
        self.exec_write_calls: list[dict[str, Any]] = []
        self.exec_resize_calls: list[dict[str, Any]] = []
        self.exec_terminate_calls: list[dict[str, Any]] = []

    async def stream_events(  # noqa: ANN201
        self,
        stop_event=None,  # noqa: ANN001
        *,
        directory: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        del directory
        for event in self._stream_events:
            if stop_event is not None and stop_event.is_set():
                break
            yield event

    async def exec_start(
        self,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        timeout_override: float | None = None,
    ) -> dict[str, Any]:
        del request, directory, timeout_override
        if self._exec_error is not None:
            raise self._exec_error
        if self._exec_start_delay > 0:
            await asyncio.sleep(self._exec_start_delay)
        return dict(self._exec_result)

    async def exec_write(
        self,
        *,
        process_id: str,
        delta_base64: str | None = None,
        close_stdin: bool | None = None,
    ) -> None:
        self.exec_write_calls.append(
            {
                "process_id": process_id,
                "delta_base64": delta_base64,
                "close_stdin": close_stdin,
            }
        )

    async def exec_resize(self, *, process_id: str, rows: int, cols: int) -> None:
        self.exec_resize_calls.append({"process_id": process_id, "rows": rows, "cols": cols})

    async def exec_terminate(self, *, process_id: str) -> None:
        self.exec_terminate_calls.append({"process_id": process_id})


@pytest.mark.asyncio
async def test_discovery_runtime_start_bridges_supported_notifications() -> None:
    request_handler = RecordingRequestHandler()
    client = DiscoveryClientStub(
        [
            {"type": "discovery.skills.changed", "properties": {}},
            {
                "type": "discovery.apps.updated",
                "properties": {"items": [{"id": "demo-app", "mention_path": "app://demo-app"}]},
            },
            {"type": "discovery.ignored", "properties": {}},
        ]
    )
    runtime = CodexDiscoveryRuntime(client=client, request_handler=request_handler)

    result = await runtime.start(
        request={"events": ["skills.changed", "apps.updated"]},
        context={"identity": "demo"},
    )

    assert result["ok"] is True
    assert request_handler.saved_task is not None
    assert request_handler.saved_task.metadata == {
        "codex": {"discovery_watch": {"events": ["apps.updated", "skills.changed"]}}
    }
    assert request_handler.saved_context == {"identity": "demo"}

    queue = DummyEventQueue()
    await request_handler.saved_producer(queue)

    artifacts = _artifact_updates(queue)
    assert [_part_data(event)["kind"] for event in artifacts] == ["skills_changed", "apps_updated"]
    assert _part_data(artifacts[1])["items"] == [
        {"id": "demo-app", "mention_path": "app://demo-app"}
    ]
    assert artifacts[0].append is False
    assert artifacts[1].append is True


@pytest.mark.asyncio
async def test_discovery_runtime_rejects_invalid_event_filters() -> None:
    runtime = CodexDiscoveryRuntime(
        client=DiscoveryClientStub([]),
        request_handler=RecordingRequestHandler(),
    )

    with pytest.raises(ValueError, match="request.events entries must be one of"):
        await runtime.start(request={"events": ["plugins.changed"]}, context=None)


@pytest.mark.asyncio
async def test_exec_runtime_start_rejects_duplicate_process_ids() -> None:
    request_handler = RecordingRequestHandler(hold_open=True)
    runtime = CodexExecRuntime(
        client=ExecClientStub(stream_events=[]),
        request_handler=request_handler,
    )

    first = await runtime.start(
        request={"command": "bash", "arguments": "-lc 'printf hello'", "processId": "exec-1"},
        directory="/workspace",
        context={"identity": "demo"},
        owner_identity="owner-1",
    )

    assert first["process_id"] == "exec-1"
    assert request_handler.saved_task.metadata == {
        "codex": {
            "exec": {
                "process_id": "exec-1",
                "command": "bash -lc 'printf hello'",
                "phase": "running",
                "tty": True,
            }
        }
    }

    with pytest.raises(ValueError, match="unique among active exec sessions"):
        await runtime.start(
            request={"command": "bash", "processId": "exec-1"},
            directory="/workspace",
            context=None,
            owner_identity="owner-1",
        )

    await request_handler.close()


@pytest.mark.asyncio
async def test_exec_runtime_streams_output_and_terminal_status() -> None:
    client = ExecClientStub(
        stream_events=[
            {
                "type": "exec.output.delta",
                "properties": {
                    "process_id": "exec-1",
                    "stream": "stdout",
                    "delta_base64": "aGVsbG8K",
                    "cap_reached": False,
                },
            },
            {
                "type": "exec.output.delta",
                "properties": {
                    "process_id": "exec-1",
                    "stream": "stderr",
                    "delta_base64": "d2FybmluZwo=",
                    "cap_reached": True,
                },
            },
        ],
        exec_result={"stdout": "hello\n", "stderr": "warning\n", "exitCode": 0},
        exec_start_delay=0.01,
    )
    runtime = CodexExecRuntime(client=client, request_handler=RecordingRequestHandler())
    handle = ExecSessionHandle(
        process_id="exec-1",
        task_id="task-1",
        context_id="ctx-1",
        stop_event=asyncio.Event(),
        command_text="bash -lc 'printf hello'",
    )
    queue = DummyEventQueue()

    await runtime._run_exec_session(  # noqa: SLF001
        handle=handle,
        request={"command": "bash", "arguments": "-lc 'printf hello'", "processId": "exec-1"},
        directory="/workspace",
        event_queue=queue,
    )

    artifacts = _artifact_updates(queue)
    assert [_part_text(event) for event in artifacts[:2]] == ["hello\n", "warning\n"]
    assert artifacts[0].append is False
    assert artifacts[1].append is False
    assert artifacts[1].last_chunk is True
    assert "exit_code: 0" in _part_text(artifacts[2])
    assert artifacts[2].last_chunk is True

    final_status = _status_updates(queue)[-1]
    assert final_status.status.state == TaskState.completed
    assert final_status.final is True
    assert final_status.metadata == {
        "codex": {
            "exec": {
                "process_id": "exec-1",
                "command": "bash -lc 'printf hello'",
                "phase": "completed",
                "exit_code": 0,
                "terminated": False,
            }
        },
        "shared": {
            "stream": {
                "source": "codex.exec.status",
                "message_id": "task-1:exec:result",
                "event_id": "task-1:status:completed",
            }
        },
    }
    assert handle.stop_event.is_set() is True


@pytest.mark.asyncio
async def test_exec_runtime_write_resize_terminate_and_failure_status() -> None:
    client = ExecClientStub(stream_events=[], exec_error=RuntimeError("boom"))
    runtime = CodexExecRuntime(client=client, request_handler=RecordingRequestHandler())
    handle = ExecSessionHandle(
        process_id="exec-1",
        task_id="task-1",
        context_id="ctx-1",
        stop_event=asyncio.Event(),
        command_text="bash",
    )
    runtime._sessions["exec-1"] = handle  # noqa: SLF001

    assert await runtime.write(
        process_id="exec-1",
        delta_base64="aGVsbG8=",
        close_stdin=False,
        owner_identity=None,
    ) == {
        "ok": True,
        "process_id": "exec-1",
    }
    assert await runtime.resize(
        process_id="exec-1",
        rows=24,
        cols=80,
        owner_identity=None,
    ) == {
        "ok": True,
        "process_id": "exec-1",
    }
    assert await runtime.terminate(process_id="exec-1", owner_identity=None) == {
        "ok": True,
        "process_id": "exec-1",
    }
    assert client.exec_write_calls == [
        {"process_id": "exec-1", "delta_base64": "aGVsbG8=", "close_stdin": False}
    ]
    assert client.exec_resize_calls == [{"process_id": "exec-1", "rows": 24, "cols": 80}]
    assert client.exec_terminate_calls == [{"process_id": "exec-1"}]

    failed_handle = ExecSessionHandle(
        process_id="exec-2",
        task_id="task-2",
        context_id="ctx-2",
        stop_event=asyncio.Event(),
        command_text="bash",
    )
    queue = DummyEventQueue()
    await runtime._run_exec_session(  # noqa: SLF001
        handle=failed_handle,
        request={"command": "bash", "processId": "exec-2"},
        directory=None,
        event_queue=queue,
    )

    final_status = _status_updates(queue)[-1]
    assert final_status.status.state == TaskState.failed
    assert final_status.final is True
    assert final_status.metadata == {
        "codex": {
            "exec": {
                "process_id": "exec-2",
                "command": "bash",
                "phase": "failed",
                "error": "boom",
            }
        }
    }


@pytest.mark.asyncio
async def test_exec_runtime_rejects_owner_mismatch_for_existing_session() -> None:
    runtime = CodexExecRuntime(
        client=ExecClientStub(stream_events=[]),
        request_handler=RecordingRequestHandler(),
    )
    runtime._sessions["exec-1"] = ExecSessionHandle(  # noqa: SLF001
        process_id="exec-1",
        task_id="task-1",
        context_id="ctx-1",
        stop_event=asyncio.Event(),
        command_text="bash",
        owner_identity="owner-a",
    )

    with pytest.raises(PermissionError, match="Exec session forbidden"):
        await runtime.write(
            process_id="exec-1",
            delta_base64="aGVsbG8=",
            close_stdin=False,
            owner_identity="owner-b",
        )
