from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task, TaskState
from sqlalchemy.ext.asyncio import AsyncEngine

from codex_a2a.config import Settings

from .database import build_database_engine

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext

logger = logging.getLogger(__name__)

TASK_STORE_ERROR_TYPE = "TASK_STORE_UNAVAILABLE"

_TERMINAL_TASK_STATES = frozenset(
    {
        TaskState.completed,
        TaskState.canceled,
        TaskState.failed,
        TaskState.rejected,
        TaskState.input_required,
        TaskState.unknown,
    }
)


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
        if incoming.model_dump(mode="json") != existing.model_dump(mode="json"):
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
        await self._inner.save(task, context)

    async def get(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        return await self._inner.get(task_id, context)

    async def delete(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> None:
        await self._inner.delete(task_id, context)


class TaskStoreOperationWrappingDecorator(TaskStoreDecorator):
    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        try:
            await self._inner.save(task, context)
        except TaskStoreOperationError:
            raise
        except Exception as exc:
            raise TaskStoreOperationError("save", task.id) from exc

    async def get(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
    ) -> Task | None:
        try:
            return await self._inner.get(task_id, context)
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
            await self._inner.delete(task_id, context)
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

    async def save(
        self,
        task: Task,
        context: ServerCallContext | None = None,
    ) -> None:
        async with self._save_lock:
            existing = await self._inner.get(task.id, context)
            decision = self._write_policy.evaluate(existing=existing, incoming=task)
            if existing is not None and existing.status.state in _TERMINAL_TASK_STATES:
                logger.warning(
                    "Received task persistence after terminal state task_id=%s existing_state=%s "
                    "incoming_state=%s persist=%s reason=%s",
                    task.id,
                    existing.status.state,
                    task.status.state,
                    decision.persist,
                    decision.reason or "accepted",
                )
            if not decision.persist:
                return
            await self._inner.save(task, context)


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
