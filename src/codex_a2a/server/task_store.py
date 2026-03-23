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


def _default_database_url(settings: Settings) -> str:
    base_path = (
        Path(settings.codex_workspace_root).expanduser()
        if settings.codex_workspace_root
        else Path.cwd()
    )
    db_path = (base_path / ".codex-a2a" / "tasks.db").resolve()
    return f"sqlite+aiosqlite:///{db_path}"


def build_task_store_runtime(settings: Settings) -> TaskStoreRuntime:
    if settings.a2a_task_store_backend == "memory":
        return TaskStoreRuntime(task_store=InMemoryTaskStore(), startup=_noop, shutdown=_noop)

    from a2a.server.tasks.database_task_store import DatabaseTaskStore
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    database_url = settings.a2a_task_store_database_url or _default_database_url(settings)
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
        create_table=settings.a2a_task_store_create_table,
        table_name=settings.a2a_task_store_table_name,
    )

    async def _startup() -> None:
        await task_store.initialize()

    async def _shutdown() -> None:
        await engine.dispose()

    return TaskStoreRuntime(task_store=task_store, startup=_startup, shutdown=_shutdown)
