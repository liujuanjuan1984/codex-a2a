from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from a2a.auth.user import UnauthenticatedUser, User
from a2a.server.cluster import (
    LegacyTaskStoreAdapter,
    StoredTask,
    TaskEventStream,
    TaskVersion,
    VersionedTaskStore,
)
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import StarletteUser
from a2a.server.tasks.copying_task_store import CopyingTaskStoreAdapter
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.authentication import SimpleUser

from codex_a2a.config import Settings

from .database import build_database_engine

TASK_STORE_ERROR_TYPE = "TASK_STORE_UNAVAILABLE"

_SDK_TASKS_TABLE_NAME = "tasks"
_SDK_TASKS_REQUIRED_COLUMNS = frozenset({"owner", "last_updated", "protocol_version"})
_SDK_TASKS_REQUIRED_INDEXES = frozenset({"idx_tasks_owner_last_updated"})
_SENSITIVE_DATABASE_QUERY_KEYS = frozenset(
    {"password", "passwd", "pwd", "token", "secret", "api_key", "apikey", "access_token"}
)


def _normalize_context(context: ServerCallContext | None) -> ServerCallContext:
    if not isinstance(context, ServerCallContext):
        return ServerCallContext()
    state = _normalized_context_state(getattr(context, "state", None))
    identity = _context_identity(state)
    normalized_user = _normalized_context_user(getattr(context, "user", None), identity=identity)
    tenant = getattr(context, "tenant", "")
    requested_extensions = getattr(context, "requested_extensions", ())
    return ServerCallContext(
        state=state,
        user=normalized_user,
        tenant=tenant if isinstance(tenant, str) else "",
        requested_extensions={
            value for value in requested_extensions if isinstance(value, str) and value
        },
    )


def _normalized_context_state(state: Any) -> MutableMapping[str, Any]:
    if isinstance(state, MutableMapping):
        return dict(state)
    return {}


def _context_identity(state: MutableMapping[str, Any]) -> str | None:
    identity = state.get("identity")
    if not isinstance(identity, str):
        return None
    normalized = identity.strip()
    return normalized or None


def _normalized_context_user(user: Any, *, identity: str | None) -> User:
    if isinstance(user, User):
        try:
            user_name = user.user_name
        except Exception:
            user_name = ""
        if isinstance(user_name, str) and user_name:
            return user
    if identity:
        return StarletteUser(SimpleUser(identity))
    return UnauthenticatedUser()


class TaskStoreOperationError(RuntimeError):
    def __init__(self, operation: str, task_id: str | None) -> None:
        self.operation = operation
        self.task_id = task_id
        target = task_id or "unknown"
        super().__init__(f"Task store {operation} failed for task_id={target}")


class TaskStoreSchemaCompatibilityError(RuntimeError):
    pass


def as_versioned_task_store(
    task_store: TaskStore | VersionedTaskStore,
) -> VersionedTaskStore:
    """Expose an unversioned store through the SDK's official adapter."""
    if isinstance(task_store, VersionedTaskStore):
        return task_store
    return LegacyTaskStoreAdapter(task_store)


async def task_store_snapshot(
    task_store: TaskStore | VersionedTaskStore,
    task_id: str,
    context: ServerCallContext | None = None,
) -> StoredTask | None:
    try:
        return await as_versioned_task_store(task_store).get(task_id, _normalize_context(context))
    except TaskStoreOperationError:
        raise
    except Exception as exc:
        raise TaskStoreOperationError("get", task_id) from exc


async def task_store_get(
    task_store: TaskStore | VersionedTaskStore,
    task_id: str,
    context: ServerCallContext | None = None,
) -> Task | None:
    stored = await task_store_snapshot(task_store, task_id, context)
    return stored.task if stored is not None else None


async def task_store_save(
    task_store: TaskStore | VersionedTaskStore,
    task: Task,
    context: ServerCallContext | None = None,
) -> TaskVersion:
    normalized_context = _normalize_context(context)
    versioned_store = as_versioned_task_store(task_store)
    try:
        stored = await versioned_store.get(task.id, normalized_context)
        return await versioned_store.save(
            task,
            event=None,
            prev=stored.task if stored is not None else None,
            prev_version=stored.version if stored is not None else TaskVersion.MISSING,
            context=normalized_context,
        )
    except TaskStoreOperationError:
        raise
    except Exception as exc:
        raise TaskStoreOperationError("save", task.id) from exc


async def task_store_delete(
    task_store: TaskStore | VersionedTaskStore,
    task_id: str,
    context: ServerCallContext | None = None,
) -> None:
    try:
        await as_versioned_task_store(task_store).delete(task_id, _normalize_context(context))
    except TaskStoreOperationError:
        raise
    except Exception as exc:
        raise TaskStoreOperationError("delete", task_id) from exc


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


@dataclass(slots=True)
class TaskStoreRuntime:
    task_store: TaskStore | VersionedTaskStore
    event_stream: TaskEventStream | None
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


def task_store_uses_database(settings: Settings) -> bool:
    return settings.a2a_database_url is not None


def describe_persistence_backend(settings: Settings) -> dict[str, str]:
    summary = {
        "backend": "memory",
        "task_store": "memory",
        "push_config_store": "memory",
        "runtime_state": "disabled",
        "database_url": "n/a",
        "sqlite_tuning": "not_applicable",
    }
    if not task_store_uses_database(settings):
        return summary

    url = make_url(cast(str, settings.a2a_database_url))
    summary.update(
        {
            "backend": "database",
            "task_store": "sdk_database",
            "push_config_store": "sdk_database",
            "runtime_state": "database",
            "database_url": _render_database_url_for_logs(url.render_as_string(hide_password=True)),
            "sqlite_tuning": (
                "local_durability_defaults"
                if url.drivername.startswith("sqlite")
                else "not_applicable"
            ),
        }
    )
    return summary


def _render_database_url_for_logs(database_url: str) -> str:
    parts = urlsplit(database_url)
    if not parts.query:
        return database_url

    redacted_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_DATABASE_QUERY_KEYS:
            redacted_query.append((key, "***"))
            continue
        redacted_query.append((key, value))
    return urlunsplit(parts._replace(query=urlencode(redacted_query)))


def build_task_store_runtime(
    settings: Settings,
    *,
    engine: AsyncEngine | None = None,
) -> TaskStoreRuntime:
    if not task_store_uses_database(settings):
        return TaskStoreRuntime(
            task_store=CopyingTaskStoreAdapter(InMemoryTaskStore()),
            event_stream=None,
            startup=_noop,
            shutdown=_noop,
        )

    from a2a.server.cluster import DatabaseTaskEventStream, VersionedDatabaseTaskStore

    resolved_engine = engine or build_database_engine(settings)
    task_store = VersionedDatabaseTaskStore(
        engine=resolved_engine,
        create_table=True,
        table_name="tasks",
    )
    raw_task_store = cast(DatabaseTaskStore, task_store.as_task_store)
    event_stream = DatabaseTaskEventStream(engine=resolved_engine)

    async def _startup() -> None:
        await _ensure_sdk_task_store_schema_compatible(raw_task_store)
        await task_store.initialize()
        await event_stream.initialize()

    async def _shutdown() -> None:
        if engine is None:
            await resolved_engine.dispose()

    return TaskStoreRuntime(
        task_store=task_store,
        event_stream=event_stream,
        startup=_startup,
        shutdown=_shutdown,
    )


async def _ensure_sdk_task_store_schema_compatible(task_store: DatabaseTaskStore) -> None:
    database_url = _render_database_url_for_logs(
        task_store.engine.url.render_as_string(hide_password=True)
    )
    async with task_store.engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: _validate_sdk_task_table_schema(
                sync_conn,
                database_url=database_url,
            )
        )


def _validate_sdk_task_table_schema(
    connection: Any,
    *,
    database_url: str,
) -> None:
    inspector = inspect(connection)
    if _SDK_TASKS_TABLE_NAME not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(_SDK_TASKS_TABLE_NAME)}
    existing_indexes = {index["name"] for index in inspector.get_indexes(_SDK_TASKS_TABLE_NAME)}
    missing_columns = sorted(_SDK_TASKS_REQUIRED_COLUMNS - existing_columns)
    missing_indexes = sorted(_SDK_TASKS_REQUIRED_INDEXES - existing_indexes)
    if not missing_columns and not missing_indexes:
        return

    details: list[str] = []
    if missing_columns:
        details.append(f"missing columns: {', '.join(missing_columns)}")
    if missing_indexes:
        details.append(f"missing indexes: {', '.join(missing_indexes)}")

    raise TaskStoreSchemaCompatibilityError(
        "Legacy SDK task table schema detected for 'tasks' "
        f"({'; '.join(details)}). Run "
        f"`a2a-db --database-url {database_url}` before starting the service. "
        "If `a2a-db` is unavailable, install the `a2a-sdk[db-cli]` extra first."
    )
