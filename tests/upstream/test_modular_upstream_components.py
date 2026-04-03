import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.upstream.conversation_facade import CodexConversationFacade
from codex_a2a.upstream.models import CodexRPCError, _PendingRpcRequest, _TurnTracker
from codex_a2a.upstream.startup import build_cli_config_args, optional_string, resolve_cli_bin
from codex_a2a.upstream.stream_bridge import (
    CodexStreamEventBridge,
    normalize_thread_status,
    normalize_thread_summary,
)
from codex_a2a.upstream.transport import CodexStdioJsonRpcTransport


def _make_conversation_facade(*, rpc_request, workspace_root="/workspace", model_id="gpt-5.2"):
    turn_trackers: dict[tuple[str, str], _TurnTracker] = {}

    def get_or_create_tracker(thread_id: str, turn_id: str) -> _TurnTracker:
        key = (thread_id, turn_id)
        tracker = turn_trackers.get(key)
        if tracker is None:
            tracker = _TurnTracker(thread_id=thread_id, turn_id=turn_id)
            turn_trackers[key] = tracker
        return tracker

    facade = CodexConversationFacade(
        workspace_root=workspace_root,
        model_id=model_id,
        rpc_request=rpc_request,
        get_or_create_tracker=get_or_create_tracker,
        turn_trackers=turn_trackers,
    )
    return facade, turn_trackers, get_or_create_tracker


@pytest.mark.asyncio
async def test_conversation_facade_overrides() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None, **_kwargs):
        seen.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thr-1"}}
        return {"turn": {"id": "turn-1"}}

    facade, _turn_trackers, tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        workspace_root="/root",
        model_id="gpt-default",
    )

    await facade.create_session(directory="/override")
    assert seen[-1][1]["cwd"] == "/override"
    assert seen[-1][1]["model"] == "gpt-default"

    tracker = tracker_factory("thr-1", "turn-1")
    tracker.completed.set()
    await facade.send_message("thr-1", "hi", directory="/dir2", timeout_seconds=1.0)
    assert seen[-1][1]["cwd"] == "/dir2"
    assert seen[-1][1]["model"] == "gpt-default"


@pytest.mark.asyncio
async def test_conversation_facade_applies_request_execution_options() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None, **_kwargs):
        seen.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thr-1"}}
        return {"turn": {"id": "turn-1"}}

    facade, _turn_trackers, tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        workspace_root="/root",
        model_id="gpt-default",
    )
    options = RequestExecutionOptions(
        model="gpt-5.2-codex",
        effort="high",
        summary="concise",
        personality="pragmatic",
    )

    await facade.create_session(directory="/override", execution_options=options)
    assert seen[-1] == (
        "thread/start",
        {
            "cwd": "/override",
            "model": "gpt-5.2-codex",
            "personality": "pragmatic",
        },
    )

    tracker = tracker_factory("thr-1", "turn-1")
    tracker.completed.set()
    await facade.send_message(
        "thr-1",
        "hi",
        directory="/dir2",
        execution_options=options,
        timeout_seconds=1.0,
    )
    assert seen[-1] == (
        "turn/start",
        {
            "threadId": "thr-1",
            "input": [{"type": "text", "text": "hi", "text_elements": []}],
            "cwd": "/dir2",
            "model": "gpt-5.2-codex",
            "effort": "high",
            "summary": "concise",
            "personality": "pragmatic",
        },
    )


@pytest.mark.asyncio
async def test_conversation_facade_lifecycle_methods_success() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None, **_kwargs):
        seen.append((method, params))
        if method == "thread/list":
            return {"data": [{"id": "thr-1", "preview": "p1"}]}
        if method == "thread/fork":
            return {"thread": {"id": "thr-1-fork", "preview": "f1"}}
        if method == "thread/unarchive":
            return {"thread": {"id": "thr-1", "preview": "p1"}}
        if method == "thread/metadata/update":
            return {"thread": {"id": "thr-1", "preview": "p1"}}
        return {}

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
    )

    sessions = await facade.list_sessions(query={"limit": 10})
    assert len(sessions) == 1
    assert sessions[0]["id"] == "thr-1"

    fork = await facade.thread_fork("thr-1", params={"ephemeral": True})
    assert fork["id"] == "thr-1-fork"

    await facade.thread_archive("thr-1")
    assert seen[-1][0] == "thread/archive"

    unarchive = await facade.thread_unarchive("thr-1")
    assert unarchive["id"] == "thr-1"

    metadata = await facade.thread_metadata_update("thr-1", params={"title": "new"})
    assert metadata["id"] == "thr-1"


@pytest.mark.asyncio
async def test_conversation_facade_create_session_passes_title_as_name() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None, **_kwargs):
        seen.append((method, params))
        return {"thread": {"id": "thr-1"}}

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        model_id=None,
    )

    await facade.create_session(title="Demo Session")
    assert seen[0] == ("thread/start", {"name": "Demo Session", "cwd": "/workspace"})


@pytest.mark.asyncio
async def test_conversation_facade_ignores_blank_session_title() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params: dict | None = None, **_kwargs):
        seen.append((method, params))
        return {"thread": {"id": "thr-1"}}

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        model_id=None,
    )

    await facade.create_session(title="   ")
    assert seen[0] == ("thread/start", {"cwd": "/workspace"})


@pytest.mark.asyncio
async def test_conversation_facade_handles_malformed_thread_responses() -> None:
    responses = iter(
        [
            None,
            {"thread": None},
            {"thread": {"id": "  "}},
            None,
            {"thread": None},
            None,
            {"thread": None},
        ]
    )

    async def fake_rpc_request(method: str, _params=None, **_kwargs):
        if method == "thread/unsubscribe":
            return {}
        return next(responses)

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        model_id=None,
    )

    with pytest.raises(RuntimeError, match="thread/start response missing result object"):
        await facade.create_session()
    with pytest.raises(RuntimeError, match="thread/start response missing thread"):
        await facade.create_session()
    with pytest.raises(RuntimeError, match="thread/start response missing thread id"):
        await facade.create_session()
    with pytest.raises(RuntimeError, match="thread/fork response missing result object"):
        await facade.thread_fork("thr-1")
    with pytest.raises(RuntimeError, match="thread/fork response missing thread"):
        await facade.thread_fork("thr-1")
    await facade.thread_unsubscribe("thr-1")
    with pytest.raises(RuntimeError, match="thread/unarchive response missing result object"):
        await facade.thread_unarchive("thr-1")
    with pytest.raises(RuntimeError, match="thread/unarchive response missing thread"):
        await facade.thread_unarchive("thr-1")


@pytest.mark.asyncio
async def test_conversation_facade_handles_message_listing_and_prompt_errors() -> None:
    responses = iter(
        [
            {"data": "bad"},
            {
                "thread": {
                    "turns": [
                        None,
                        {"items": None},
                        {
                            "items": [
                                None,
                                {"type": "toolCall", "id": "skip-me"},
                                {"type": "userMessage", "id": "", "text": "skip"},
                                {"type": "agentMessage", "id": "m-1", "text": None},
                                {"type": "userMessage", "id": "m-2", "text": "hello"},
                            ]
                        },
                    ]
                }
            },
            None,
            {"turn": None},
            {"turn": {"id": " "}},
        ]
    )

    async def fake_rpc_request(_method: str, _params=None, **_kwargs):
        return next(responses)

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
        workspace_root=None,
        model_id=None,
    )

    assert await facade.list_sessions(query={"limit": "oops"}) == []
    assert await facade.list_messages("thr-1", query={"limit": "bad"}) == [
        {
            "info": {"id": "m-1", "role": "assistant"},
            "parts": [{"type": "text", "text": ""}],
            "raw": {"type": "agentMessage", "id": "m-1", "text": None},
        },
        {
            "info": {"id": "m-2", "role": "user"},
            "parts": [{"type": "text", "text": "hello"}],
            "raw": {"type": "userMessage", "id": "m-2", "text": "hello"},
        },
    ]

    with pytest.raises(RuntimeError, match="turn/start response missing result object"):
        await facade.session_prompt_async("thr-1", {"parts": [{"type": "text", "text": "hi"}]})
    with pytest.raises(RuntimeError, match="turn/start response missing turn"):
        await facade.session_prompt_async("thr-1", {"parts": [{"type": "text", "text": "hi"}]})
    with pytest.raises(RuntimeError, match="turn/start response missing turn id"):
        await facade.session_prompt_async("thr-1", {"parts": [{"type": "text", "text": "hi"}]})


@pytest.mark.asyncio
async def test_conversation_facade_send_message_cleans_up_after_error_and_timeout() -> None:
    async def fake_rpc_request(_method: str, _params=None, **_kwargs):
        return {"turn": {"id": "turn-1"}}

    facade, turn_trackers, tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
    )
    tracker = tracker_factory("thr-1", "turn-1")
    tracker.error = "permission denied"
    tracker.completed.set()

    with pytest.raises(RuntimeError, match="codex turn failed: permission denied"):
        await facade.send_message("thr-1", "hello", timeout_seconds=0.1)
    assert ("thr-1", "turn-1") not in turn_trackers

    with pytest.raises(RuntimeError, match="codex turn did not complete before timeout"):
        await facade.send_message("thr-1", "hello", timeout_seconds=0.01)
    assert ("thr-1", "turn-1") not in turn_trackers


@pytest.mark.asyncio
async def test_conversation_facade_session_command_and_shell_errors() -> None:
    seen: list[tuple[str, dict | None]] = []

    async def fake_rpc_request(method: str, params=None, **_kwargs):
        seen.append((method, params))
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        return None

    facade, _turn_trackers, tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
    )
    tracker = tracker_factory("thr-1", "turn-1")
    tracker.text_chunks.append("ok")
    tracker.completed.set()

    message = await facade.session_command(
        "thr-1",
        {"command": "review", "arguments": "--all"},
        timeout_seconds=None,
    )

    assert message.text == "ok"
    assert seen[0] == (
        "turn/start",
        {
            "threadId": "thr-1",
            "input": [{"type": "text", "text": "/review --all", "text_elements": []}],
            "cwd": "/workspace",
            "model": "gpt-5.2",
        },
    )

    with pytest.raises(RuntimeError, match="shell command must not be empty"):
        await facade.session_shell("thr-1", {"command": "   "})
    with pytest.raises(RuntimeError, match="command/exec response missing result object"):
        await facade.session_shell("thr-1", {"command": "pwd"})


@pytest.mark.asyncio
async def test_conversation_facade_turn_and_review_control_methods() -> None:
    seen: list[tuple[str, dict | None]] = []
    responses = iter(
        [
            {"turnId": "turn-9"},
            {
                "turn": {"id": "turn-review-1", "status": "inProgress"},
                "reviewThreadId": "thr-1-review",
            },
            {
                "turn": {"id": "turn-review-inline-1", "status": "inProgress"},
            },
        ]
    )

    async def fake_rpc_request(method: str, params=None, **_kwargs):
        seen.append((method, params))
        return next(responses)

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
    )

    steer_result = await facade.turn_steer(
        "thr-1",
        expected_turn_id="turn-9",
        request={"parts": [{"type": "text", "text": "Focus on the failing tests first."}]},
    )
    detached_review = await facade.review_start(
        "thr-1",
        target={"type": "commit", "sha": "commit-demo-123"},
        delivery="detached",
    )
    inline_review = await facade.review_start(
        "thr-1",
        target={"type": "uncommittedChanges"},
        delivery="inline",
    )

    assert seen[0] == (
        "turn/steer",
        {
            "threadId": "thr-1",
            "input": [
                {
                    "type": "text",
                    "text": "Focus on the failing tests first.",
                    "text_elements": [],
                }
            ],
            "expectedTurnId": "turn-9",
        },
    )
    assert seen[1] == (
        "review/start",
        {
            "threadId": "thr-1",
            "target": {"type": "commit", "sha": "commit-demo-123"},
            "delivery": "detached",
        },
    )
    assert seen[2] == (
        "review/start",
        {
            "threadId": "thr-1",
            "target": {"type": "uncommittedChanges"},
            "delivery": "inline",
        },
    )
    assert steer_result == {"ok": True, "thread_id": "thr-1", "turn_id": "turn-9"}
    assert detached_review["review_thread_id"] == "thr-1-review"
    assert inline_review["review_thread_id"] == "thr-1"


@pytest.mark.asyncio
async def test_conversation_facade_turn_and_review_control_errors() -> None:
    responses = iter(
        [
            None,
            {"turnId": "  "},
            None,
            {"turn": None},
            {"turn": {"id": "  "}},
            {"turn": {"id": "turn-review-1"}},
        ]
    )

    async def fake_rpc_request(_method: str, _params=None, **_kwargs):
        return next(responses)

    facade, _turn_trackers, _tracker_factory = _make_conversation_facade(
        rpc_request=fake_rpc_request,
    )

    with pytest.raises(RuntimeError, match="turn/steer response missing result object"):
        await facade.turn_steer(
            "thr-1",
            expected_turn_id="turn-9",
            request={"parts": [{"type": "text", "text": "hello"}]},
        )
    with pytest.raises(RuntimeError, match="turn/steer response missing turn id"):
        await facade.turn_steer(
            "thr-1",
            expected_turn_id="turn-9",
            request={"parts": [{"type": "text", "text": "hello"}]},
        )
    with pytest.raises(RuntimeError, match="review/start response missing result object"):
        await facade.review_start(
            "thr-1",
            target={"type": "commit", "sha": "abc"},
            delivery="detached",
        )
    with pytest.raises(RuntimeError, match="review/start response missing turn"):
        await facade.review_start(
            "thr-1",
            target={"type": "commit", "sha": "abc"},
            delivery="detached",
        )
    with pytest.raises(RuntimeError, match="review/start response missing turn id"):
        await facade.review_start(
            "thr-1",
            target={"type": "commit", "sha": "abc"},
            delivery="detached",
        )
    with pytest.raises(RuntimeError, match="review/start response missing review thread id"):
        await facade.review_start(
            "thr-1",
            target={"type": "commit", "sha": "abc"},
            delivery="detached",
        )


def test_stream_bridge_normalization_helpers_cover_invalid_shapes() -> None:
    assert normalize_thread_status({"type": "running"}) == {"type": "running"}
    assert normalize_thread_status({"type": "   "}) is None
    assert normalize_thread_status("idle") == {"type": "idle"}
    assert normalize_thread_status(None) is None

    assert normalize_thread_summary(None) is None
    assert normalize_thread_summary({"id": "  "}) is None
    assert normalize_thread_summary({"id": "thr-1", "name": " Demo "}) == {
        "id": "thr-1",
        "title": "Demo",
        "raw": {"id": "thr-1", "name": " Demo "},
    }


@pytest.mark.asyncio
async def test_stream_bridge_queue_full_timeout_cleanup_and_error_events() -> None:
    bridge = CodexStreamEventBridge(event_queue_maxsize=1)

    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=1)
    queue.put_nowait({"type": "old"})
    bridge.event_subscribers.add(queue)

    await bridge.enqueue_stream_event({"type": "new"})
    assert queue.get_nowait() == {"type": "new"}
    bridge.event_subscribers.discard(queue)

    stop_event = asyncio.Event()

    async def trigger_stop() -> None:
        await asyncio.sleep(0.01)
        stop_event.set()

    asyncio.create_task(trigger_stop())
    observed: list[dict[str, object]] = []
    async for event in bridge.stream_events(stop_event=stop_event):
        observed.append(event)
    assert observed == []
    assert not bridge.event_subscribers

    events: list[dict[str, object]] = []

    async def fake_emit(event: dict[str, object]) -> None:
        events.append(event)

    await bridge.handle_notification(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thr-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "hello",
            },
        },
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {
            "method": "item/reasoning/summaryTextDelta",
            "params": {
                "threadId": "thr-1",
                "itemId": "reasoning-1",
                "delta": "thinking",
            },
        },
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thr-1",
                "tokenUsage": {
                    "last": {
                        "inputTokens": 10,
                        "outputTokens": 4,
                        "totalTokens": 14,
                        "reasoningOutputTokens": 2,
                        "cachedInputTokens": 1,
                    }
                },
            },
        },
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {
            "method": "turn/started",
            "params": {"threadId": "thr-1", "turn": {"id": "turn-2"}},
        },
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thr-1",
                "turn": {"id": "turn-2", "status": "failed", "error": {"message": "boom"}},
            },
        },
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {"method": "error", "params": {"message": "broken"}},
        enqueue_stream_event=fake_emit,
    )

    assert [event["type"] for event in events] == [
        "message.part.updated",
        "message.part.updated",
        "message.finalized",
        "turn.lifecycle.started",
        "turn.lifecycle.completed",
        "codex.error",
    ]
    delta_tracker = bridge.turn_trackers[("thr-1", "turn-1")]
    failed_tracker = bridge.turn_trackers[("thr-1", "turn-2")]
    assert delta_tracker.message_id == "msg-1"
    assert delta_tracker.text == "hello"
    assert failed_tracker.error == "boom"
    assert failed_tracker.completed.is_set() is True


@pytest.mark.asyncio
async def test_stream_bridge_filters_invalid_discovery_and_thread_notifications() -> None:
    bridge = CodexStreamEventBridge(event_queue_maxsize=1)
    events: list[dict[str, object]] = []

    async def fake_emit(event: dict[str, object]) -> None:
        events.append(event)

    await bridge.handle_notification({"params": {}}, enqueue_stream_event=fake_emit)
    await bridge.handle_notification(
        {"method": "ignored", "params": None},
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {"method": "app/list/updated", "params": {"data": [None, {"id": "app-only"}]}},
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {"method": "thread/started", "params": {"thread": {"preview": "missing id"}}},
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {"method": "thread/status/changed", "params": {"threadId": "", "status": "running"}},
        enqueue_stream_event=fake_emit,
    )
    await bridge.handle_notification(
        {"method": "thread/archived", "params": {"threadId": ""}},
        enqueue_stream_event=fake_emit,
    )

    assert events == [{"type": "discovery.apps.updated", "properties": {"items": []}}]


@pytest.mark.asyncio
async def test_transport_handles_response_errors_timeouts_and_shutdown_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = CodexStdioJsonRpcTransport(
        listen="stdio://",
        startup_cli_args=["-c", 'profile="coding"'],
        log_payloads=False,
    )

    process = MagicMock()
    process.returncode = None
    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock()
    transport.process = process

    original_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout):
        if timeout == 1.5:
            awaitable.close()
            raise TimeoutError
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr("codex_a2a.upstream.transport.asyncio.wait_for", fake_wait_for)

    loop = asyncio.get_running_loop()
    pending_future: asyncio.Future[object] = loop.create_future()
    transport.pending_requests = {
        "1": _PendingRpcRequest(
            request_id="1",
            method="thread/list",
            future=pending_future,
            correlation_id="corr-1",
        )
    }

    await transport.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert isinstance(pending_future.exception(), RuntimeError)

    error_future: asyncio.Future[object] = loop.create_future()
    transport.pending_requests = {
        "7": _PendingRpcRequest(
            request_id="7",
            method="thread/list",
            future=error_future,
            correlation_id="corr-7",
        )
    }
    handled = await transport.dispatch_response(
        {"id": 7, "error": {"code": 401, "message": "denied", "data": {"scope": "session"}}}
    )
    assert handled is True
    exc = error_future.exception()
    assert isinstance(exc, CodexRPCError)
    assert exc.code == 401
    assert exc.data == {"scope": "session"}
    assert await transport.dispatch_response({"id": 999, "result": {}}) is True
    assert await transport.dispatch_response({"method": "thread/started"}) is False

    transport.process = None
    with pytest.raises(RuntimeError, match="codex app-server is not running"):
        await transport.send_json_message({"method": "initialized", "params": {}})

    async def fake_send_json_message(_payload: dict[str, object]) -> None:
        return None

    transport.send_json_message = fake_send_json_message

    with pytest.raises(RuntimeError, match="requires an ensure_started callback"):
        await transport.rpc_request("thread/list")

    with pytest.raises(RuntimeError, match="codex rpc timeout: thread/list"):
        await transport.rpc_request(
            "thread/list",
            skip_ensure=True,
            timeout_seconds=0.01,
        )
    assert transport.pending_requests == {}


@pytest.mark.asyncio
async def test_transport_stream_helpers_cover_empty_streams_and_partial_lines() -> None:
    transport = CodexStdioJsonRpcTransport(
        listen="stdio://",
        startup_cli_args=[],
        log_payloads=False,
    )

    await transport.read_stdout_loop(dispatch_message=AsyncMock())
    await transport.read_stderr_loop()

    class _PartialStream:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = list(chunks)

        async def read(self, _size: int) -> bytes:
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

    lines = [
        line
        async for line in transport._iter_stream_lines(
            _PartialStream([b'{"id":1}\n{"id":2}', b"\ntrailing"])
        )
    ]
    assert lines == [b'{"id":1}', b'{"id":2}', b"trailing"]


def test_startup_helpers_cover_optional_strings_cli_args_and_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert optional_string(None) is None
    assert optional_string("  demo  ") == "demo"
    assert optional_string("   ") is None
    assert build_cli_config_args({"profile": "coding", "enabled": True}) == [
        "-c",
        'profile="coding"',
        "-c",
        "enabled=true",
    ]

    monkeypatch.setattr("codex_a2a.upstream.startup.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "codex_a2a.upstream.startup.os.path.exists",
        lambda path: path == os.path.expanduser("~/.npm-global/bin/codex"),
    )
    monkeypatch.setattr(
        "codex_a2a.upstream.startup.os.access",
        lambda path, mode: path == os.path.expanduser("~/.npm-global/bin/codex"),
    )
    assert resolve_cli_bin("codex") == os.path.expanduser("~/.npm-global/bin/codex")

    monkeypatch.setattr("codex_a2a.upstream.startup.os.path.exists", lambda _path: True)
    monkeypatch.setattr("codex_a2a.upstream.startup.os.access", lambda _path, _mode: False)
    with pytest.raises(Exception, match="is not executable"):
        resolve_cli_bin("~/bin/codex")
