from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Table, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateColumn


@dataclass(frozen=True, slots=True)
class SchemaMigration:
    version: int
    description: str
    upgrade: Callable[[Any], None]


def _validate_add_column_support(*, table: Table, column_name: str) -> None:
    column = table.c[column_name]
    if column.primary_key or not column.nullable:
        raise RuntimeError(f"Unsupported schema migration for {table.name}.{column_name}")


def add_missing_columns(
    sync_conn: Any,
    *,
    table: Table,
    column_names: Sequence[str],
) -> None:
    inspector = inspect(sync_conn)
    existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
    table_name = sync_conn.dialect.identifier_preparer.format_table(table)
    for column_name in column_names:
        if column_name in existing_columns:
            continue
        _validate_add_column_support(table=table, column_name=column_name)
        column = table.c[column_name]
        rendered_column = str(CreateColumn(column).compile(dialect=sync_conn.dialect)).strip()
        sync_conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {rendered_column}")
        existing_columns.add(column_name)


def read_schema_version(
    sync_conn: Any,
    *,
    version_table: Table,
    scope: str,
) -> int | None:
    return sync_conn.execute(
        select(version_table.c.version).where(version_table.c.scope == scope)
    ).scalar_one_or_none()


def write_schema_version(
    sync_conn: Any,
    *,
    version_table: Table,
    scope: str,
    version: int,
) -> None:
    existing_version = read_schema_version(sync_conn, version_table=version_table, scope=scope)
    if existing_version is not None:
        sync_conn.execute(
            update(version_table).where(version_table.c.scope == scope).values(version=version)
        )
        return
    try:
        sync_conn.execute(insert(version_table).values(scope=scope, version=version))
    except IntegrityError:
        sync_conn.execute(
            update(version_table).where(version_table.c.scope == scope).values(version=version)
        )


def apply_schema_migrations(
    sync_conn: Any,
    *,
    scope: str,
    current_version: int,
    version_table: Table,
    migrations: Mapping[int, SchemaMigration],
) -> None:
    if current_version < 0:
        raise ValueError("current_version must be non-negative")

    current_schema_version = read_schema_version(
        sync_conn,
        version_table=version_table,
        scope=scope,
    )
    if current_schema_version is not None and current_schema_version > current_version:
        raise RuntimeError(
            f"Schema scope {scope!r} is at version {current_schema_version}, "
            f"but runtime only supports up to {current_version}."
        )

    starting_version = current_schema_version or 0
    for next_version in range(starting_version + 1, current_version + 1):
        migration = migrations.get(next_version)
        if migration is None:
            raise RuntimeError(
                f"Missing migration for schema scope {scope!r} version {next_version}."
            )
        migration.upgrade(sync_conn)

    if current_schema_version != current_version:
        write_schema_version(
            sync_conn,
            version_table=version_table,
            scope=scope,
            version=current_version,
        )
