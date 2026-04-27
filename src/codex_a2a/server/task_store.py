from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState, a2a_pb2
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import class_mapper

from codex_a2a.a2a_proto import proto_to_python
from codex_a2a.config import Settings

from .database import build_database_engine

logger = logging.getLogger(__name__)

TASK_STORE_ERROR_TYPE = "TASK_STORE_UNAVAILABLE"

_TERMINAL_TASK_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_REJECTED,
        TaskState.TASK_STATE_UNSPECIFIED,
    }
)
_TERMINAL_TASK_STATE_VALUES = tuple(
    a2a_pb2.TaskState.Name(state) for state in _TERMINAL_TASK_STATES
)
_ATOMIC_TERMINAL_GUARD_DIALECTS = frozenset({"postgresql", "sqlite"})


def _normalize_context(context: ServerCallContext | None) -> ServerCallContext:
    return context if isinstance(context, ServerCallContext) else ServerCallContext()


class TaskStoreOperationError(RuntimeError):
    def __init__(self, operation: str, task_id: str | None) -> None:
        self.operation = operation
        self.task_id = task_id
        target = task_id or "unknown"
        super().__init__(f"Task store {operation} failed for task_id={target}")


@dataclass(frozen=True)
class TaskPersistenceDecision:
    persist: bool
    reason: str | None = None


class TaskWritePolicy(ABC):
    @abstractmethod
    def evaluate(
        self,
        *,
        existing: Task | None,
        incoming: Task,
    ) -> TaskPersistenceDecision: ...


class FirstTerminalStateWinsPolicy(TaskWritePolicy):
    def evaluate(
        self,
        *,
        existing: Task | None,
        incoming: Task,
    ) -> TaskPersistenceDecision:
        if existing is None or existing.status.state not in _TERMINAL_TASK_STATES:
            return TaskPersistenceDecision(persist=True)
        if incoming.status.state != existing.status.state:
            return TaskPersistenceDecision(
                persist=False,
                reason="state_overwrite_after_terminal_persistence",
            )
        if proto_to_python(incoming) != proto_to_python(existing):
            return TaskPersistenceDecision(
                persist=False,
                reason="late_mutation_after_terminal_persistence",
            )
        return TaskPersistenceDecision(
            persist=False,
            reason="duplicate_terminal_persistence",
        )


class TaskStoreDecorator(TaskStore):
    def __init__(self, inner: TaskStore) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        await self._inner.save(task, _normalize_context(context))

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext | None = None,
    ) -> ListTasksResponse:
        return await self._inner.list(params, _normalize_context(context))

    async def get(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        return await self._inner.get(task_id, _normalize_context(context))

    async def delete(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> None:
        await self._inner.delete(task_id, _normalize_context(context))


class TaskStoreOperationWrappingDecorator(TaskStoreDecorator):
    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        try:
            await self._inner.save(task, _normalize_context(context))
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("save", task.id) from exc

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext | None = None,
    ) -> ListTasksResponse:
        try:
            return await self._inner.list(params, _normalize_context(context))
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("list", None) from exc

    async def get(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        try:
            return await self._inner.get(task_id, _normalize_context(context))
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("get", task_id) from exc

    async def delete(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> None:
        try:
            await self._inner.delete(task_id, _normalize_context(context))
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("delete", task_id) from exc


class PolicyAwareTaskStore(TaskStoreDecorator):
    def __init__(
        self,
        inner: TaskStore,
        *,
        write_policy: TaskWritePolicy | None = None,
    ) -> None:
        super().__init__(inner)
        self._write_policy = write_policy or FirstTerminalStateWinsPolicy()
        self._save_lock = asyncio.Lock()
        self._atomic_guard_fallback_logged = False

    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        context = _normalize_context(context)
        raw_task_store = unwrap_task_store(self._inner)
        if isinstance(raw_task_store, DatabaseTaskStore):
            await self._save_database_task(raw_task_store, task, context)
            return

        await self._save_with_read_before_write(task, context)

    async def _save_with_read_before_write(
        self,
        task: Task,
        context: ServerCallContext,
    ) -> None:
        async with self._save_lock:
            existing = await self._inner.get(task.id, context)
            decision = self._write_policy.evaluate(existing=existing, incoming=task)
            self._log_terminal_persistence_decision(
                existing=existing, incoming=task, decision=decision
            )
            if not decision.persist:
                return
            await self._inner.save(task, context)

    async def _save_database_task(
        self,
        task_store: DatabaseTaskStore,
        task: Task,
        context: ServerCallContext,
    ) -> None:
        dialect_name = task_store.engine.dialect.name
        if dialect_name not in _ATOMIC_TERMINAL_GUARD_DIALECTS:
            if not self._atomic_guard_fallback_logged:
                logger.warning(
                    "Database-backed task store dialect does not support atomic terminal guard; "
                    "falling back to read-before-write policy dialect=%s",
                    dialect_name,
                )
                self._atomic_guard_fallback_logged = True
            await self._save_with_read_before_write(task, context)
            return

        try:
            if await self._persist_with_atomic_terminal_guard(task_store, task, context):
                return
            existing = await self._load_task_from_database(task_store, task.id, context)
            decision = self._write_policy.evaluate(existing=existing, incoming=task)
            self._log_terminal_persistence_decision(
                existing=existing, incoming=task, decision=decision
            )
            if not decision.persist:
                return
            raise RuntimeError(
                "Atomic task persistence was skipped without an authoritative terminal task."
            )
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("save", task.id) from exc

    async def _persist_with_atomic_terminal_guard(
        self,
        task_store: DatabaseTaskStore,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> bool:
        await task_store._ensure_initialized()
        owner = task_store.owner_resolver(
            context if isinstance(context, ServerCallContext) else ServerCallContext()
        )
        statement = _build_atomic_task_save_statement(
            task_store=task_store,
            task=task,
            owner=owner,
            task_table=task_store.task_model.__table__,
            dialect_name=task_store.engine.dialect.name,
        )
        async with task_store.async_session_maker.begin() as session:
            result = await session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def _load_task_from_database(
        self,
        task_store: DatabaseTaskStore,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        await task_store._ensure_initialized()
        owner = task_store.owner_resolver(
            context if isinstance(context, ServerCallContext) else ServerCallContext()
        )
        async with task_store.async_session_maker() as session:
            stmt = select(task_store.task_model).where(
                task_store.task_model.id == task_id,
                task_store.task_model.owner == owner,
            )
            result = await session.execute(stmt)
            task_model = result.scalar_one_or_none()
        if task_model is None:
            return None
        return task_store._from_orm(task_model)

    def _log_terminal_persistence_decision(
        self,
        *,
        existing: Task | None,
        incoming: Task,
        decision: TaskPersistenceDecision,
    ) -> None:
        if existing is None or existing.status.state not in _TERMINAL_TASK_STATES:
            return
        logger.warning(
            "Received task persistence after terminal state task_id=%s existing_state=%s "
            "incoming_state=%s persist=%s reason=%s",
            incoming.id,
            existing.status.state,
            incoming.status.state,
            decision.persist,
            decision.reason or "accepted",
        )


class GuardedTaskStore(PolicyAwareTaskStore):
    def __init__(
        self,
        inner: TaskStore,
        *,
        write_policy: TaskWritePolicy | None = None,
    ) -> None:
        super().__init__(
            TaskStoreOperationWrappingDecorator(inner),
            write_policy=write_policy,
        )


def build_task_store_failure_metadata(operation: str) -> dict[str, Any]:
    return {"codex": {"error": {"type": TASK_STORE_ERROR_TYPE, "operation": operation}}}


def task_store_failure_message(operation: str) -> str:
    if operation == "get":
        return "Task store unavailable while loading task state."
    if operation == "save":
        return "Task store unavailable while persisting task state."
    if operation == "delete":
        return "Task store unavailable while deleting task state."
    return "Task store unavailable."


def unwrap_task_store(task_store: TaskStore) -> TaskStore:
    inner = getattr(task_store, "_inner", None)
    if isinstance(inner, TaskStore):
        return unwrap_task_store(inner)
    return task_store


def _build_atomic_task_save_statement(
    *,
    task_store: DatabaseTaskStore,
    task: Task,
    owner: str,
    task_table: Any,
    dialect_name: str,
):
    insert = _resolve_atomic_insert_factory(dialect_name)
    values = _task_row_values(task_store, task, owner)
    status_state = task_table.c.status["state"].as_string()
    persist_guard = or_(
        task_table.c.status.is_(None),
        status_state.is_(None),
        status_state.not_in(_TERMINAL_TASK_STATE_VALUES),
    )
    return (
        insert(task_table)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[task_table.c.id],
            set_={key: value for key, value in values.items() if key != "id"},
            where=persist_guard,
        )
        .returning(task_table.c.id)
    )


def _resolve_atomic_insert_factory(dialect_name: str):
    if dialect_name == "sqlite":
        return sqlite_insert
    if dialect_name == "postgresql":
        return postgresql_insert
    raise ValueError(f"Unsupported atomic task persistence dialect: {dialect_name}")


def _task_row_values(task_store: DatabaseTaskStore, task: Task, owner: str) -> dict[str, Any]:
    db_task = task_store._to_orm(task, owner)
    values: dict[str, Any] = {}
    for column_attr in class_mapper(task_store.task_model).column_attrs:
        values[column_attr.columns[0].name] = getattr(db_task, column_attr.key)
    return values


@dataclass(slots=True)
class TaskStoreRuntime:
    task_store: TaskStore
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


def task_store_uses_database(settings: Settings) -> bool:
    return settings.a2a_database_url is not None


def build_task_store_runtime(
    settings: Settings,
    *,
    engine: AsyncEngine | None = None,
) -> TaskStoreRuntime:
    if not task_store_uses_database(settings):
        return TaskStoreRuntime(
            task_store=GuardedTaskStore(InMemoryTaskStore()), startup=_noop, shutdown=_noop
        )

    from a2a.server.tasks.database_task_store import DatabaseTaskStore

    resolved_engine = engine or build_database_engine(settings)
    raw_task_store = DatabaseTaskStore(
        engine=resolved_engine,
        create_table=True,
        table_name="tasks",
    )
    task_store = GuardedTaskStore(raw_task_store)

    async def _startup() -> None:
        await raw_task_store.initialize()

    async def _shutdown() -> None:
        if engine is None:
            await resolved_engine.dispose()

    return TaskStoreRuntime(task_store=task_store, startup=_startup, shutdown=_shutdown)
