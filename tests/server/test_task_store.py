from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.context import ServerCallContext
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task, TaskState, TaskStatus

from codex_a2a.a2a_proto import proto_to_python
from codex_a2a.server.database import build_database_engine
from codex_a2a.server.task_store import (
    GuardedTaskStore,
    TaskStoreOperationError,
    TaskStoreSchemaCompatibilityError,
    build_task_store_runtime,
    describe_persistence_backend,
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


def test_describe_persistence_backend_reports_memory_defaults() -> None:
    summary = describe_persistence_backend(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=None,
        )
    )

    assert summary == {
        "backend": "memory",
        "task_store": "memory",
        "push_config_store": "memory",
        "runtime_state": "disabled",
        "database_url": "n/a",
        "sqlite_tuning": "not_applicable",
    }


def test_describe_persistence_backend_reports_database_configuration(tmp_path: Path) -> None:
    summary = describe_persistence_backend(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=(
                f"sqlite+aiosqlite:///{(tmp_path / 'summary.db').resolve()}?password=secret"
            ),
        )
    )

    assert summary["backend"] == "database"
    assert summary["task_store"] == "sdk_database"
    assert summary["push_config_store"] == "sdk_database"
    assert summary["runtime_state"] == "database"
    assert summary["database_url"].startswith("sqlite+aiosqlite:///")
    assert "secret" not in summary["database_url"]
    assert summary["sqlite_tuning"] == "local_durability_defaults"


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
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
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
    assert restored.status.state == TaskState.TASK_STATE_WORKING


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
async def test_task_store_runtime_rejects_legacy_sdk_task_table_schema(tmp_path: Path) -> None:
    database_path = (tmp_path / "legacy-tasks.db").resolve()
    database_url = f"sqlite+aiosqlite:///{database_path}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, context_id TEXT, kind TEXT)")
        connection.commit()
    finally:
        connection.close()

    runtime = build_task_store_runtime(settings)
    try:
        with pytest.raises(TaskStoreSchemaCompatibilityError, match="Legacy SDK task table schema"):
            await runtime.startup()
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_guarded_task_store_allows_input_required_to_resume_working() -> None:
    task_store = GuardedTaskStore(InMemoryTaskStore())

    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
    )
    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
        )
    )
    await task_store.save(
        Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )
    )

    restored = await task_store.get("task-1")

    assert restored is not None
    assert restored.status.state == TaskState.TASK_STATE_WORKING


@pytest.mark.asyncio
async def test_guarded_task_store_drops_late_terminal_mutation() -> None:
    task_store = GuardedTaskStore(InMemoryTaskStore())
    authoritative = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
    )
    mutated = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        metadata={"codex": {"late_mutation": True}},
    )

    await task_store.save(authoritative)
    await task_store.save(mutated)

    restored = await task_store.get("task-1")

    assert restored is not None
    assert proto_to_python(restored.metadata) == {}


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
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )
        await first_runtime.task_store.save(
            Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
            )
        )
        await second_runtime.task_store.save(
            Task(
                id="task-1",
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )

        restored = await first_runtime.task_store.get("task-1")
    finally:
        await first_runtime.shutdown()
        await second_runtime.shutdown()

    assert restored is not None
    assert restored.status.state == TaskState.TASK_STATE_WORKING


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
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
    )
    late_mutation = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        metadata={"codex": {"late_mutation": True}},
    )
    stale_snapshot = Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
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
    assert restored.status.state == TaskState.TASK_STATE_COMPLETED
    assert proto_to_python(restored.metadata) == {}


@pytest.mark.asyncio
async def test_guarded_database_task_store_normalizes_context_with_identity_only(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'identity-only-context.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    runtime = build_task_store_runtime(settings)
    await runtime.startup()
    try:
        context_user_a = MagicMock(spec=ServerCallContext)
        context_user_a.state = {"identity": "user-a"}
        context_user_a.tenant = ""
        context_user_a.requested_extensions = set()

        context_user_b = MagicMock(spec=ServerCallContext)
        context_user_b.state = {"identity": "user-b"}
        context_user_b.tenant = ""
        context_user_b.requested_extensions = set()

        task = Task(
            id="task-1",
            context_id="ctx-1",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )

        await runtime.task_store.save(task, context_user_a)

        restored = await runtime.task_store.get("task-1", context_user_a)
        other_identity = await runtime.task_store.get("task-1", context_user_b)
    finally:
        await runtime.shutdown()

    assert restored is not None
    assert restored.id == "task-1"
    assert other_identity is None


class _BrokenTaskStore(TaskStore):
    async def save(self, task: Task, context=None) -> None:  # noqa: ANN001
        del task, context
        raise RuntimeError("broken save")

    async def list(self, params, context=None):  # noqa: ANN001
        del params, context
        raise RuntimeError("broken list")

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
        status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
    )

    task_store = GuardedTaskStore(_BrokenTaskStore())
    with pytest.raises(TaskStoreOperationError, match="Task store get failed for task_id=task-1"):
        await task_store.get("task-1")

    class _SaveBrokenTaskStore(TaskStore):
        async def save(self, task: Task, context=None) -> None:  # noqa: ANN001
            del task, context
            raise RuntimeError("broken save")

        async def list(self, params, context=None):  # noqa: ANN001
            del params, context
            raise RuntimeError("broken list")

        async def get(self, task_id: str, context=None) -> Task | None:  # noqa: ANN001
            del context
            return Task(
                id=task_id,
                context_id="ctx-1",
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
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
