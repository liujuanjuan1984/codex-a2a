from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

import codex_a2a.server.runtime_state as runtime_state_module
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.server.runtime_state_schema import _PENDING_INTERRUPT_REQUESTS
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_insert_then_update_on_conflict_recovers_from_concurrent_first_insert_race() -> None:
    executed: list[str] = []

    class _FakeSession:
        async def execute(self, clause):  # noqa: ANN001
            executed.append(clause.__visit_name__)
            if clause.__visit_name__ == "insert":
                raise IntegrityError("insert", {}, Exception("duplicate key"))
            if clause.__visit_name__ == "update":
                return None
            raise AssertionError(f"Unexpected clause type: {clause.__visit_name__}")

    await runtime_state_module._insert_then_update_on_conflict(
        _FakeSession(),
        table=_PENDING_INTERRUPT_REQUESTS,
        key_values={"request_id": "perm-1"},
        update_values={
            "interrupt_type": "permission",
            "session_id": "ses-1",
            "identity": "user-1",
            "task_id": "task-1",
            "context_id": "ctx-1",
            "created_at": 1.0,
            "expires_at": 2.0,
            "tombstone_expires_at": None,
            "rpc_request_id": "rpc-1",
            "params": {},
        },
    )

    assert executed == ["insert", "update"]


@pytest.mark.asyncio
async def test_thread_watch_state_store_refcounts_shared_subscription(tmp_path) -> None:
    database_path = (tmp_path / "runtime.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    assert runtime_state.state_store is not None
    store = runtime_state.state_store
    try:
        acquired_1 = await store.acquire_thread_watch(
            watch_id="watch-1",
            owner_identity="user-1",
            task_id="watch-1",
            context_id="ctx-1",
            subscription_key="sub-1",
            connection_scope="scope-1",
            event_filter=("thread.started",),
            thread_filter=("thr-1",),
        )
        acquired_2 = await store.acquire_thread_watch(
            watch_id="watch-2",
            owner_identity="user-2",
            task_id="watch-2",
            context_id="ctx-2",
            subscription_key="sub-1",
            connection_scope="scope-1",
            event_filter=("thread.started",),
            thread_filter=("thr-1",),
        )

        assert acquired_1.subscription.owner_count == 1
        assert acquired_2.subscription.owner_count == 2

        released_1 = await store.release_thread_watch(
            watch_id="watch-1",
            release_reason="task_cancel",
        )
        subscription_after_first_release = await store.load_thread_watch_subscription(
            subscription_key="sub-1"
        )
        owner_after_first_release = await store.load_thread_watch_owner(watch_id="watch-1")

        assert released_1.owner_released is True
        assert released_1.remaining_owner_count == 1
        assert released_1.subscription_released is False
        assert owner_after_first_release is not None
        assert owner_after_first_release.status == "released"
        assert subscription_after_first_release is not None
        assert subscription_after_first_release.owner_count == 1
        assert subscription_after_first_release.status == "active"

        released_2 = await store.release_thread_watch(
            watch_id="watch-2",
            release_reason="task_cancel",
        )
        subscription_after_second_release = await store.load_thread_watch_subscription(
            subscription_key="sub-1"
        )

        assert released_2.remaining_owner_count == 0
        assert released_2.subscription_released is True
        assert subscription_after_second_release is not None
        assert subscription_after_second_release.owner_count == 0
        assert subscription_after_second_release.status == "released"
    finally:
        await runtime_state.shutdown()
