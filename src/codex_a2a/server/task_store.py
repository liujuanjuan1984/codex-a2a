from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore

from codex_a2a.config import Settings


@dataclass(slots=True)
class TaskStoreRuntime:
    task_store: TaskStore
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


def build_task_store_runtime(settings: Settings) -> TaskStoreRuntime:
    use_database_backend = settings.a2a_task_store_backend == "database" or (
        settings.a2a_task_store_backend == "auto" and settings.a2a_database_url is not None
    )
    if not use_database_backend:
        return TaskStoreRuntime(task_store=InMemoryTaskStore(), startup=_noop, shutdown=_noop)

    from a2a.server.tasks.database_task_store import DatabaseTaskStore
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    database_url = settings.a2a_database_url
    if database_url is None:  # pragma: no cover - guarded by Settings validation
        raise ValueError("Database task store requires A2A_DATABASE_URL to be configured")
    url = make_url(database_url)

    if url.drivername.startswith("sqlite"):
        database_path = url.database
        if database_path and database_path != ":memory:" and not database_path.startswith("file:"):
            path = Path(database_path)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        database_url,
        pool_pre_ping=not url.drivername.startswith("sqlite"),
    )
    task_store = DatabaseTaskStore(
        engine=engine,
        create_table=settings.a2a_database_auto_create,
        table_name="tasks",
    )

    async def _startup() -> None:
        await task_store.initialize()

    async def _shutdown() -> None:
        await engine.dispose()

    return TaskStoreRuntime(task_store=task_store, startup=_startup, shutdown=_shutdown)
