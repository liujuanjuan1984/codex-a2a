from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from a2a.server.tasks.database_push_notification_config_store import (
    DatabasePushNotificationConfigStore,
)
from a2a.server.tasks.inmemory_push_notification_config_store import (
    InMemoryPushNotificationConfigStore,
)

from codex_a2a.server.database import build_database_engine
from codex_a2a.server.push_config_store import build_push_config_store_runtime
from tests.support.settings import make_settings


def test_build_push_config_store_runtime_uses_memory_backend_when_database_disabled() -> None:
    runtime = build_push_config_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=None,
        )
    )

    assert isinstance(runtime.push_config_store, InMemoryPushNotificationConfigStore)


def test_build_push_config_store_runtime_uses_database_backend_when_database_enabled(
    tmp_path: Path,
) -> None:
    runtime = build_push_config_store_runtime(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'push-configs.db').resolve()}",
        )
    )

    assert isinstance(runtime.push_config_store, DatabasePushNotificationConfigStore)


@pytest.mark.asyncio
async def test_push_config_store_runtime_does_not_dispose_shared_engine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'push-configs-shared.db').resolve()}"
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=database_url,
    )
    engine = build_database_engine(settings)
    dispose_spy = AsyncMock()
    monkeypatch.setattr(type(engine), "dispose", dispose_spy)

    runtime = build_push_config_store_runtime(settings, engine=engine)
    await runtime.shutdown()

    dispose_spy.assert_not_awaited()
