from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest

from codex_a2a.execution.session_runtime import SessionRuntime
from codex_a2a.server.database import build_database_engine
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from tests.support.settings import make_settings


@pytest.mark.asyncio
async def test_session_binding_and_owner_restore_from_database(tmp_path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        runtime_1 = SessionRuntime(
            session_cache_ttl_seconds=3600,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        session_id, pending = await runtime_1.get_or_create_session(
            identity="user-1",
            context_id="ctx-1",
            title="hello",
            preferred_session_id=None,
            create_session=lambda: _return_session("session-1"),
        )

        runtime_2 = SessionRuntime(
            session_cache_ttl_seconds=3600,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        restored = await runtime_2.binding_snapshot(identity="user-1", context_id="ctx-1")
    finally:
        await runtime_state.shutdown()

    assert session_id == "session-1"
    assert pending is False
    assert restored.session_id == "session-1"
    assert restored.owner_identity == "user-1"
    assert restored.pending_identity is None


@pytest.mark.asyncio
async def test_pending_session_claim_restore_from_database(tmp_path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        runtime_1 = SessionRuntime(
            session_cache_ttl_seconds=3600,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        claimed = await runtime_1.claim_session(identity="user-2", session_id="external-1")

        runtime_2 = SessionRuntime(
            session_cache_ttl_seconds=3600,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        restored = await runtime_2.session_claim_snapshot(session_id="external-1")
        await runtime_2.finalize_session_claim(identity="user-2", session_id="external-1")
        finalized = await runtime_2.session_claim_snapshot(session_id="external-1")
    finally:
        await runtime_state.shutdown()

    assert claimed is True
    assert restored.pending_identity == "user-2"
    assert restored.owner_identity is None
    assert finalized.owner_identity == "user-2"
    assert finalized.pending_identity is None


@pytest.mark.asyncio
async def test_database_binding_survives_session_cache_ttl_expiry(tmp_path) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'runtime.db').resolve()}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    try:
        runtime_1 = SessionRuntime(
            session_cache_ttl_seconds=1,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        session_id, pending = await runtime_1.get_or_create_session(
            identity="user-1",
            context_id="ctx-1",
            title="hello",
            preferred_session_id=None,
            create_session=lambda: _return_session("session-1"),
        )

        await runtime_1.bound_session_for(identity="user-1", context_id="ctx-1")
        await runtime_1.session_owner_matches(identity="user-1", session_id="session-1")
        await asyncio.sleep(1.1)

        runtime_2 = SessionRuntime(
            session_cache_ttl_seconds=1,
            session_cache_maxsize=1000,
            state_store=runtime_state.state_store,
        )
        restored = await runtime_2.binding_snapshot(identity="user-1", context_id="ctx-1")
    finally:
        await runtime_state.shutdown()

    assert session_id == "session-1"
    assert pending is False
    assert restored.session_id == "session-1"
    assert restored.owner_identity == "user-1"


@pytest.mark.asyncio
async def test_new_runtime_state_schema_omits_binding_and_owner_expires_at_columns(
    tmp_path,
) -> None:
    database_path = (tmp_path / "runtime.db").resolve()
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    runtime_state = build_runtime_state_runtime(settings)
    await runtime_state.startup()
    await runtime_state.shutdown()

    binding_columns = _sqlite_columns(database_path, "a2a_session_bindings")
    owner_columns = _sqlite_columns(database_path, "a2a_session_owners")
    pending_claim_columns = _sqlite_columns(database_path, "a2a_pending_session_claims")

    assert "expires_at" not in binding_columns
    assert "expires_at" not in owner_columns
    assert "expires_at" in pending_claim_columns


@pytest.mark.asyncio
async def test_runtime_state_runtime_does_not_dispose_shared_engine(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'shared-runtime.db').resolve()}",
    )
    engine = build_database_engine(settings)
    dispose_spy = AsyncMock()
    monkeypatch.setattr(type(engine), "dispose", dispose_spy)

    runtime_state = build_runtime_state_runtime(settings, engine=engine)
    await runtime_state.shutdown()

    dispose_spy.assert_not_awaited()


async def _return_session(session_id: str) -> str:
    return session_id


def _sqlite_columns(database_path, table_name: str) -> set[str]:  # noqa: ANN001
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row[1]) for row in rows}
    finally:
        connection.close()
