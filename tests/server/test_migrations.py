from __future__ import annotations

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

import codex_a2a.server.migrations as migrations_module
from codex_a2a.server.runtime_state import _PENDING_INTERRUPT_REQUESTS


def test_add_missing_columns_supports_non_sqlite_dialects(monkeypatch) -> None:
    executed: list[str] = []

    class _FakeInspector:
        def get_columns(self, _table_name: str) -> list[dict[str, str]]:
            return []

    class _FakeConnection:
        def __init__(self) -> None:
            self.dialect = postgresql_dialect()

        def exec_driver_sql(self, statement: str) -> None:
            executed.append(statement)

    monkeypatch.setattr(migrations_module, "inspect", lambda _connection: _FakeInspector())

    migrations_module.add_missing_columns(
        _FakeConnection(),
        table=_PENDING_INTERRUPT_REQUESTS,
        column_names=("identity",),
    )

    assert executed == ["ALTER TABLE a2a_pending_interrupt_requests ADD COLUMN identity VARCHAR"]


def test_add_missing_columns_rejects_non_nullable_columns(monkeypatch) -> None:
    class _FakeInspector:
        def get_columns(self, _table_name: str) -> list[dict[str, str]]:
            return []

    class _FakeConnection:
        def __init__(self) -> None:
            self.dialect = postgresql_dialect()

        def exec_driver_sql(self, statement: str) -> None:
            raise AssertionError(f"unexpected DDL execution: {statement}")

    monkeypatch.setattr(migrations_module, "inspect", lambda _connection: _FakeInspector())

    with pytest.raises(
        RuntimeError,
        match="Unsupported schema migration for a2a_pending_interrupt_requests.session_id",
    ):
        migrations_module.add_missing_columns(
            _FakeConnection(),
            table=_PENDING_INTERRUPT_REQUESTS,
            column_names=("session_id",),
        )
