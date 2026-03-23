import asyncio

import pytest

from codex_a2a.execution.session_runtime import SessionRuntime


@pytest.mark.asyncio
async def test_binding_snapshot_reflects_created_session_owner() -> None:
    runtime = SessionRuntime(
        session_cache_ttl_seconds=3600,
        session_cache_maxsize=10,
    )

    async def create_session() -> str:
        return "session-1"

    session_id, pending = await runtime.get_or_create_session(
        identity="user-1",
        context_id="context-A",
        title="hello",
        preferred_session_id=None,
        create_session=create_session,
    )

    assert session_id == "session-1"
    assert pending is False

    binding = await runtime.binding_snapshot(identity="user-1", context_id="context-A")
    assert binding.session_id == "session-1"
    assert binding.owner_identity == "user-1"
    assert binding.pending_identity is None


@pytest.mark.asyncio
async def test_binding_snapshot_reflects_finalize_preferred_session_binding() -> None:
    runtime = SessionRuntime(
        session_cache_ttl_seconds=3600,
        session_cache_maxsize=10,
    )

    session_id, pending = await runtime.get_or_create_session(
        identity="user-1",
        context_id="context-A",
        title="hello",
        preferred_session_id="session-X",
        create_session=lambda: asyncio.sleep(0, result="unexpected"),
    )

    assert session_id == "session-X"
    assert pending is True

    claim = await runtime.session_claim_snapshot(session_id="session-X")
    assert claim.owner_identity is None
    assert claim.pending_identity == "user-1"

    await runtime.finalize_preferred_session_binding(
        identity="user-1",
        context_id="context-A",
        session_id="session-X",
    )

    binding = await runtime.binding_snapshot(identity="user-1", context_id="context-A")
    assert binding.session_id == "session-X"
    assert binding.owner_identity == "user-1"
    assert binding.pending_identity is None


@pytest.mark.asyncio
async def test_running_execution_snapshot_tracks_and_clears_request() -> None:
    runtime = SessionRuntime(
        session_cache_ttl_seconds=3600,
        session_cache_maxsize=10,
    )
    stop_event = asyncio.Event()
    running_task = asyncio.create_task(asyncio.sleep(10))

    await runtime.track_running_request(
        task_id="task-1",
        context_id="context-A",
        identity="user-1",
        task=running_task,
        stop_event=stop_event,
    )

    snapshot = await runtime.running_execution_snapshot(
        task_id="task-1",
        context_id="context-A",
    )
    assert snapshot is not None
    assert snapshot.identity == "user-1"
    assert snapshot.task is running_task
    assert snapshot.stop_event is stop_event

    await runtime.untrack_running_request(task_id="task-1", context_id="context-A")
    assert (
        await runtime.running_execution_snapshot(task_id="task-1", context_id="context-A")
        is None
    )

    running_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running_task
