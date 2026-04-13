from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
)

from .migrations import SchemaMigration, add_missing_columns, apply_schema_migrations

_STATE_METADATA = MetaData()
_RUNTIME_STATE_SCHEMA_SCOPE = "runtime_state"
CURRENT_RUNTIME_STATE_SCHEMA_VERSION = 3

_SESSION_BINDINGS = Table(
    "a2a_session_bindings",
    _STATE_METADATA,
    Column("identity", String, primary_key=True),
    Column("context_id", String, primary_key=True),
    Column("session_id", String, nullable=False),
)

_SESSION_OWNERS = Table(
    "a2a_session_owners",
    _STATE_METADATA,
    Column("session_id", String, primary_key=True),
    Column("owner_identity", String, nullable=False),
)

_PENDING_SESSION_CLAIMS = Table(
    "a2a_pending_session_claims",
    _STATE_METADATA,
    Column("session_id", String, primary_key=True),
    Column("pending_identity", String, nullable=False),
    Column("expires_at", Float, nullable=False),
)

_PENDING_INTERRUPT_REQUESTS = Table(
    "a2a_pending_interrupt_requests",
    _STATE_METADATA,
    Column("request_id", String, primary_key=True),
    Column("interrupt_type", String, nullable=False),
    Column("session_id", String, nullable=False),
    Column("identity", String, nullable=True),
    Column("credential_id", String, nullable=True),
    Column("task_id", String, nullable=True),
    Column("context_id", String, nullable=True),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=True),
    Column("tombstone_expires_at", Float, nullable=True),
    Column("rpc_request_id", JSON, nullable=False),
    Column("params", JSON, nullable=False),
)

_THREAD_WATCH_OWNERS = Table(
    "a2a_thread_watch_owners",
    _STATE_METADATA,
    Column("watch_id", String, primary_key=True),
    Column("owner_identity", String, nullable=False),
    Column("task_id", String, nullable=False),
    Column("context_id", String, nullable=False),
    Column("subscription_key", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("released_at", Float, nullable=True),
    Column("release_reason", String, nullable=True),
)

_THREAD_WATCH_SUBSCRIPTIONS = Table(
    "a2a_thread_watch_subscriptions",
    _STATE_METADATA,
    Column("subscription_key", String, primary_key=True),
    Column("connection_scope", String, nullable=False),
    Column("owner_count", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("event_filter", JSON, nullable=True),
    Column("thread_filter", JSON, nullable=True),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("released_at", Float, nullable=True),
)

_SCHEMA_VERSION = Table(
    "a2a_schema_version",
    _STATE_METADATA,
    Column("scope", String, primary_key=True),
    Column("version", Integer, nullable=False),
)


def _upgrade_runtime_state_schema_to_v1(sync_conn: Any) -> None:
    add_missing_columns(
        sync_conn,
        table=_PENDING_INTERRUPT_REQUESTS,
        column_names=(
            "identity",
            "task_id",
            "context_id",
            "expires_at",
            "tombstone_expires_at",
        ),
    )


def _upgrade_runtime_state_schema_to_v3(sync_conn: Any) -> None:
    add_missing_columns(
        sync_conn,
        table=_PENDING_INTERRUPT_REQUESTS,
        column_names=("credential_id",),
    )


_RUNTIME_STATE_MIGRATIONS = {
    1: SchemaMigration(
        version=1,
        description="Add persisted interrupt binding metadata and expiry columns.",
        upgrade=_upgrade_runtime_state_schema_to_v1,
    ),
    2: SchemaMigration(
        version=2,
        description="Add persisted thread watch owner and shared subscription state tables.",
        upgrade=lambda _conn: None,
    ),
    3: SchemaMigration(
        version=3,
        description="Add persisted interrupt credential identifiers.",
        upgrade=_upgrade_runtime_state_schema_to_v3,
    ),
}


def apply_runtime_state_schema_migrations(sync_conn: Any) -> None:
    apply_schema_migrations(
        sync_conn,
        scope=_RUNTIME_STATE_SCHEMA_SCOPE,
        current_version=CURRENT_RUNTIME_STATE_SCHEMA_VERSION,
        version_table=_SCHEMA_VERSION,
        migrations=_RUNTIME_STATE_MIGRATIONS,
    )


def initialize_runtime_state_schema(sync_conn: Any) -> None:
    _STATE_METADATA.create_all(sync_conn)
    apply_runtime_state_schema_migrations(sync_conn)
