from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task, TaskState, TaskStatus

from codex_a2a.server.database import build_database_engine
from codex_a2a.server.task_store import (
    GuardedTaskStore,
    TaskStoreOperationError,
    build_task_store_runtime,
    unwrap_task_store,
)
from tests.support.settings import make_settings


def test_build_task_store_runtime_uses_memory_backend_when_database_disabled() -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=None,
        )
    )

    assert isinstance(runtime.task_store, GuardedTaskStore)
    assert isinstance(unwrap_task_store(runtime.task_store), InMemoryTaskStore)


def test_build_task_store_runtime_uses_database_backend_when_database_enabled(
    tmp_path: Path,
) -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'default-runtime.db').resolve()}",
        )
    )

    assert isinstance(runtime.task_store, GuardedTaskStore)
    assert isinstance(unwrap_task_store(runtime.task_store), DatabaseTaskStore)


@pytest.mark.asyncio
async def test_database_task_store_persists_tasks_across_runtime_rebuilds(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'tasks.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )

    first_runtime = build_task_store_runtime(settings)
    assert isinstance(first_runtime.task_store, GuardedTaskStore)
    assert isinstance(unwrap_task_store(first_runtime.task_store), DatabaseTaskStore)
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


@pytest.mark.asyncio
async def test_guarded_task_store_allows_input_required_to_resume_working() -> None:
    task_store = GuardedTaskStore(InMemoryTaskStore())

    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.working),
        )
    )
    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.input_required),
        )
    )
    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.working),
        )
    )

    restored = await task_store.get("task-1")

    assert restored is not None
    assert restored.status.state == TaskState.working


@pytest.mark.asyncio
async def test_guarded_task_store_drops_late_terminal_mutation() -> None:
    task_store = GuardedTaskStore(InMemoryTaskStore())
    authoritative = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.completed),
    )
    mutated = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.completed),
        metadata={"codex": {"late_mutation": True}},
    )

    await task_store.save(authoritative)
    await task_store.save(mutated)

    restored = await task_store.get("task-1")

    assert restored is not None
    assert restored.metadata is None


@pytest.mark.asyncio
async def test_guarded_database_task_store_resumes_from_input_required(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'terminal-guard.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    first_runtime = build_task_store_runtime(settings)
    second_runtime = build_task_store_runtime(settings)
    await first_runtime.startup()
    await second_runtime.startup()
    try:
        await first_runtime.task_store.save(
            Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.working),
            )
        )
        await first_runtime.task_store.save(
            Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.input_required),
            )
        )
        await second_runtime.task_store.save(
            Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.working),
            )
        )

        restored = await first_runtime.task_store.get("task-1")
    finally:
        await first_runtime.shutdown()
        await second_runtime.shutdown()

    assert restored is not None
    assert restored.status.state == TaskState.working


@pytest.mark.asyncio
async def test_guarded_database_task_store_does_not_depend_on_stale_read_before_terminal_drop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'stale-read-guard.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    authoritative = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.completed),
    )
    late_mutation = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.completed),
        metadata={"codex": {"late_mutation": True}},
    )
    stale_snapshot = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.working),
    )

    first_runtime = build_task_store_runtime(settings)
    second_runtime = build_task_store_runtime(settings)
    await first_runtime.startup()
    await second_runtime.startup()
    try:
        await first_runtime.task_store.save(stale_snapshot)
        await first_runtime.task_store.save(authoritative)

        raw_second = unwrap_task_store(second_runtime.task_store)
        assert isinstance(raw_second, DatabaseTaskStore)
        original_get = DatabaseTaskStore.get.__get__(raw_second, DatabaseTaskStore)

        async def _stale_get(task_id: str, context=None) -> Task | None:  # noqa: ANN001
            del context
            if task_id == "task-1":
                return stale_snapshot
            return None

        monkeypatch.setattr(raw_second, "get", _stale_get)
        await second_runtime.task_store.save(late_mutation)
        monkeypatch.setattr(raw_second, "get", original_get)

        restored = await first_runtime.task_store.get("task-1")
    finally:
        await first_runtime.shutdown()
        await second_runtime.shutdown()

    assert restored is not None
    assert restored.status.state == TaskState.completed
    assert restored.metadata is None


class _BrokenTaskStore(TaskStore):
    async def save(self, task: Task, context=None) -> None:  # noqa: ANN001
        del task, context
        raise RuntimeError("broken save")

    async def get(self, task_id: str, context=None) -> Task | None:  # noqa: ANN001
        del task_id, context
        raise RuntimeError("broken get")

    async def delete(self, task_id: str, context=None) -> None:  # noqa: ANN001
        del task_id, context
        raise RuntimeError("broken delete")


@pytest.mark.asyncio
async def test_guarded_task_store_wraps_operation_failures() -> None:
    task = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.working),
    )

    task_store = GuardedTaskStore(_BrokenTaskStore())
    with pytest.raises(TaskStoreOperationError, match="Task store get failed for task_id=task-1"):
        await task_store.get("task-1")

    class _SaveBrokenTaskStore(TaskStore):
        async def save(self, task: Task, context=None) -> None:  # noqa: ANN001
            del task, context
            raise RuntimeError("broken save")

        async def get(self, task_id: str, context=None) -> Task | None:  # noqa: ANN001
            del context
            return Task(
                id=task_id,
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.working),
            )

        async def delete(self, task_id: str, context=None) -> None:  # noqa: ANN001
            del task_id, context

    task_store = GuardedTaskStore(_SaveBrokenTaskStore())
    with pytest.raises(TaskStoreOperationError, match="Task store save failed for task_id=task-1"):
        await task_store.save(task)

    task_store = GuardedTaskStore(_BrokenTaskStore())
    with pytest.raises(
        TaskStoreOperationError,
        match="Task store delete failed for task_id=task-1",
    ):
        await task_store.delete("task-1")
