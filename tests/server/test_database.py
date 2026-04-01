from __future__ import annotations

import pytest

from codex_a2a.server.database import build_database_engine
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_build_database_engine_configures_sqlite_pragmas(tmp_path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    engine = build_database_engine(settings)

    try:
        async with engine.connect() as conn:
            journal_mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
            synchronous = (await conn.exec_driver_sql("PRAGMA synchronous")).scalar_one()
    finally:
        await engine.dispose()

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 30_000
    assert int(synchronous) == 1
