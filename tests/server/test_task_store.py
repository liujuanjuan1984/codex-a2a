from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from a2a.server.cluster import (
    ConcurrentTaskModificationError,
    LegacyTaskStoreAdapter,
    TaskVersion,
    VersionedDatabaseTaskStore,
    VersionedTaskStore,
)
from a2a.server.context import ServerCallContext
from a2a.server.tasks.copying_task_store import CopyingTaskStoreAdapter
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState, TaskStatus

from codex_a2a.server.database import build_database_engine
from codex_a2a.server.task_store import (
    TaskStoreOperationError,
    TaskStoreSchemaCompatibilityError,
    as_versioned_task_store,
    build_task_store_runtime,
    describe_persistence_backend,
    task_store_delete,
    task_store_get,
    task_store_save,
    task_store_snapshot,
)
from tests.support.settings import make_settings


def _task(state: TaskState = TaskState.TASK_STATE_WORKING) -> Task:
    return Task(
        id="task-1",
        context_id="ctx-1",
        status=TaskStatus(state=state),
    )


def test_build_task_store_runtime_uses_sdk_adapters_for_memory_backend() -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=None,
        )
    )

    assert isinstance(runtime.task_store, CopyingTaskStoreAdapter)
    assert isinstance(as_versioned_task_store(runtime.task_store), LegacyTaskStoreAdapter)
    assert runtime.event_stream is None


def test_build_task_store_runtime_uses_native_versioned_store_for_database(
    tmp_path: Path,
) -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
        )
    )

    assert isinstance(runtime.task_store, VersionedDatabaseTaskStore)
    assert isinstance(runtime.task_store.as_task_store, DatabaseTaskStore)
    assert as_versioned_task_store(runtime.task_store) is runtime.task_store
    assert runtime.event_stream is not None


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
    await first_runtime.startup()
    try:
        await task_store_save(first_runtime.task_store, _task())
    finally:
        await first_runtime.shutdown()

    second_runtime = build_task_store_runtime(settings)
    await second_runtime.startup()
    try:
        restored = await task_store_get(second_runtime.task_store, "task-1")
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
    original_dispose = engine.dispose
    dispose_spy = MagicMock()
    monkeypatch.setattr(type(engine), "dispose", dispose_spy)

    try:
        runtime = build_task_store_runtime(settings, engine=engine)
        await runtime.shutdown()

        dispose_spy.assert_not_called()
    finally:
        await original_dispose()


@pytest.mark.asyncio
async def test_task_store_runtime_rejects_legacy_sdk_task_table_schema(tmp_path: Path) -> None:
    database_path = (tmp_path / "legacy-tasks.db").resolve()
    database_url = f"sqlite+aiosqlite:///{database_path}?password=secret"
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
        with pytest.raises(
            TaskStoreSchemaCompatibilityError,
            match="Legacy SDK task table schema",
        ) as exc_info:
            await runtime.startup()
    finally:
        await runtime.shutdown()

    assert "secret" not in str(exc_info.value)
    assert "password=%2A%2A%2A" in str(exc_info.value)


@pytest.mark.asyncio
async def test_input_required_task_can_resume_working_with_memory_adapter() -> None:
    runtime = build_task_store_runtime(
        make_settings(a2a_bearer_token="test-token", a2a_database_url=None)
    )

    await task_store_save(runtime.task_store, _task())
    await task_store_save(
        runtime.task_store,
        _task(TaskState.TASK_STATE_INPUT_REQUIRED),
    )
    await task_store_save(runtime.task_store, _task())

    restored = await task_store_get(runtime.task_store, "task-1")

    assert restored is not None
    assert restored.status.state == TaskState.TASK_STATE_WORKING


@pytest.mark.asyncio
async def test_native_database_store_rejects_stale_version_writes(tmp_path: Path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'versioned.db').resolve()}",
    )
    runtime = build_task_store_runtime(settings)
    await runtime.startup()
    try:
        await task_store_save(runtime.task_store, _task())
        snapshot = await task_store_snapshot(
            runtime.task_store,
            "task-1",
            ServerCallContext(),
        )
        assert snapshot is not None

        completed = _task(TaskState.TASK_STATE_COMPLETED)
        await runtime.task_store.save(
            completed,
            event=None,
            prev=snapshot.task,
            prev_version=snapshot.version,
            context=ServerCallContext(),
        )

        late_mutation = _task(TaskState.TASK_STATE_COMPLETED)
        late_mutation.metadata["late"] = True
        with pytest.raises(ConcurrentTaskModificationError):
            await runtime.task_store.save(
                late_mutation,
                event=None,
                prev=snapshot.task,
                prev_version=snapshot.version,
                context=ServerCallContext(),
            )

        restored = await task_store_get(
            runtime.task_store,
            "task-1",
            ServerCallContext(),
        )
    finally:
        await runtime.shutdown()

    assert restored is not None
    assert restored.status.state == TaskState.TASK_STATE_COMPLETED
    assert not restored.metadata


@pytest.mark.asyncio
async def test_versioned_store_helpers_validate_owner_scope(tmp_path: Path) -> None:
    runtime = build_task_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'identity.db').resolve()}",
        )
    )
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

        await task_store_save(runtime.task_store, _task(), context_user_a)
        restored = await task_store_get(runtime.task_store, "task-1", context_user_a)
        other_identity = await task_store_get(runtime.task_store, "task-1", context_user_b)
    finally:
        await runtime.shutdown()

    assert restored is not None
    assert restored.id == "task-1"
    assert other_identity is None


class _BrokenVersionedTaskStore(VersionedTaskStore):
    async def save(
        self,
        task: Task,
        *,
        event=None,
        prev=None,
        prev_version: TaskVersion,
        context: ServerCallContext,
    ) -> TaskVersion:
        del task, event, prev, prev_version, context
        raise RuntimeError("broken save")

    async def get(self, task_id: str, context: ServerCallContext):
        del task_id, context
        raise RuntimeError("broken get")

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext,
    ) -> ListTasksResponse:
        del params, context
        raise RuntimeError("broken list")

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        del task_id, context
        raise RuntimeError("broken delete")


@pytest.mark.asyncio
async def test_versioned_store_helpers_wrap_operation_failures() -> None:
    task_store = _BrokenVersionedTaskStore()

    with pytest.raises(
        TaskStoreOperationError,
        match="Task store get failed for task_id=task-1",
    ):
        await task_store_get(task_store, "task-1")

    with pytest.raises(
        TaskStoreOperationError,
        match="Task store save failed for task_id=task-1",
    ):
        await task_store_save(task_store, _task())

    with pytest.raises(
        TaskStoreOperationError,
        match="Task store delete failed for task_id=task-1",
    ):
        await task_store_delete(task_store, "task-1")
