from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from a2a.server.tasks.database_push_notification_config_store import (
    DatabasePushNotificationConfigStore,
)
from a2a.server.tasks.inmemory_push_notification_config_store import (
    InMemoryPushNotificationConfigStore,
)
from a2a.server.tasks.push_notification_config_store import PushNotificationConfigStore
from sqlalchemy.ext.asyncio import AsyncEngine

from codex_a2a.config import Settings

from .database import build_database_engine


@dataclass(slots=True)
class PushConfigStoreRuntime:
    push_config_store: PushNotificationConfigStore
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


def push_config_store_uses_database(settings: Settings) -> bool:
    return settings.a2a_database_url is not None


def build_push_config_store_runtime(
    settings: Settings,
    *,
    engine: AsyncEngine | None = None,
) -> PushConfigStoreRuntime:
    if not push_config_store_uses_database(settings):
        return PushConfigStoreRuntime(
            push_config_store=InMemoryPushNotificationConfigStore(),
            startup=_noop,
            shutdown=_noop,
        )

    resolved_engine = engine or build_database_engine(settings)
    raw_push_config_store = DatabasePushNotificationConfigStore(
        engine=resolved_engine,
        create_table=True,
        table_name="push_notification_configs",
    )

    async def _startup() -> None:
        await raw_push_config_store.initialize()

    async def _shutdown() -> None:
        if engine is None:
            await resolved_engine.dispose()

    return PushConfigStoreRuntime(
        push_config_store=raw_push_config_store,
        startup=_startup,
        shutdown=_shutdown,
    )
