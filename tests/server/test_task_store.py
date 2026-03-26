from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import Task, TaskState, TaskStatus

from codex_a2a.server.database import build_database_engine
from codex_a2a.server.task_store import build_task_store_runtime
from tests.support.settings import make_settings


def test_build_task_store_runtime_uses_memory_backend_when_database_disabled() -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=None,
        )
    )

    assert isinstance(runtime.task_store, InMemoryTaskStore)


def test_build_task_store_runtime_uses_database_backend_by_default() -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
        )
    )

    assert isinstance(runtime.task_store, DatabaseTaskStore)


@pytest.mark.asyncio
async def test_database_task_store_persists_tasks_across_runtime_rebuilds(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'tasks.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )

    first_runtime = build_task_store_runtime(settings)
    assert isinstance(first_runtime.task_store, DatabaseTaskStore)
    await first_runtime.startup()
    try:
        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.working),
        )
        await first_runtime.task_store.save(task)
    finally:
        await first_runtime.shutdown()

    second_runtime = build_task_store_runtime(settings)
    await second_runtime.startup()
    try:
        restored = await second_runtime.task_store.get("task-1")
    finally:
        await second_runtime.shutdown()

    assert restored is not None
    assert restored.id == "task-1"
    assert restored.context_id == "ctx-1"
    assert restored.status.state == TaskState.working


@pytest.mark.asyncio
async def test_task_store_runtime_does_not_dispose_shared_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'tasks-shared.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    engine = build_database_engine(settings)
    dispose_spy = AsyncMock()
    monkeypatch.setattr(type(engine), "dispose", dispose_spy)

    runtime = build_task_store_runtime(settings, engine=engine)
    await runtime.shutdown()

    dispose_spy.assert_not_awaited()
