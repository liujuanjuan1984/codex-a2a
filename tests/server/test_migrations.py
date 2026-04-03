from __future__ import annotations

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.exc import IntegrityError

import codex_a2a.server.migrations as migrations_module
from codex_a2a.server.runtime_state import _PENDING_INTERRUPT_REQUESTS, _SCHEMA_VERSION


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


def test_write_schema_version_recovers_from_concurrent_first_insert_race() -> None:
    executed: list[str] = []

    class _FakeResult:
        def __init__(self, value: int | None) -> None:
            self._value = value

        def scalar_one_or_none(self) -> int | None:
            return self._value

    class _FakeConnection:
        def execute(self, clause):  # noqa: ANN001
            executed.append(clause.__visit_name__)
            if clause.__visit_name__ == "select":
                return _FakeResult(None)
            if clause.__visit_name__ == "insert":
                raise IntegrityError("insert", {}, Exception("duplicate key"))
            if clause.__visit_name__ == "update":
                return None
            raise AssertionError(f"Unexpected clause type: {clause.__visit_name__}")

    migrations_module.write_schema_version(
        _FakeConnection(),
        version_table=_SCHEMA_VERSION,
        scope="runtime_state",
        version=1,
    )

    assert executed == ["select", "insert", "update"]


def test_apply_schema_migrations_writes_schema_version_after_each_step(monkeypatch) -> None:
    executed: list[str] = []

    monkeypatch.setattr(
        migrations_module,
        "read_schema_version",
        lambda *_args, **_kwargs: 0,
    )

    def _record_write(*_args, scope: str, version: int, **_kwargs) -> None:
        executed.append(f"write:{scope}:{version}")

    monkeypatch.setattr(migrations_module, "write_schema_version", _record_write)

    migrations_module.apply_schema_migrations(
        object(),
        scope="runtime_state",
        current_version=2,
        version_table=_SCHEMA_VERSION,
        migrations={
            1: migrations_module.SchemaMigration(
                version=1,
                description="step-1",
                upgrade=lambda _conn: executed.append("migration:1"),
            ),
            2: migrations_module.SchemaMigration(
                version=2,
                description="step-2",
                upgrade=lambda _conn: executed.append("migration:2"),
            ),
        },
    )

    assert executed == [
        "migration:1",
        "write:runtime_state:1",
        "migration:2",
        "write:runtime_state:2",
    ]
