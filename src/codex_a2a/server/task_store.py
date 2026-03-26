from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from sqlalchemy.ext.asyncio import AsyncEngine

from codex_a2a.config import Settings

from .database import build_database_engine


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
        return TaskStoreRuntime(task_store=InMemoryTaskStore(), startup=_noop, shutdown=_noop)

    from a2a.server.tasks.database_task_store import DatabaseTaskStore

    resolved_engine = engine or build_database_engine(settings)
    task_store = DatabaseTaskStore(
        engine=resolved_engine,
        create_table=settings.a2a_database_auto_create,
        table_name="tasks",
    )

    async def _startup() -> None:
        await task_store.initialize()

    async def _shutdown() -> None:
        if engine is None:
            await resolved_engine.dispose()

    return TaskStoreRuntime(task_store=task_store, startup=_startup, shutdown=_shutdown)
