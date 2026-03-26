from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from codex_a2a.config import Settings


def build_database_engine(settings: Settings) -> AsyncEngine:
    database_url = settings.a2a_database_url
    if database_url is None:
        raise ValueError("A2A_DATABASE_URL is required to build a database engine")

    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        database_path = url.database
        if database_path and database_path != ":memory:" and not database_path.startswith("file:"):
            path = Path(database_path)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)

    return create_async_engine(
        database_url,
        pool_pre_ping=not url.drivername.startswith("sqlite"),
    )
