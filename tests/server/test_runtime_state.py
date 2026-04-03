from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

import codex_a2a.server.runtime_state as runtime_state_module
from codex_a2a.server.runtime_state import _PENDING_INTERRUPT_REQUESTS


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
