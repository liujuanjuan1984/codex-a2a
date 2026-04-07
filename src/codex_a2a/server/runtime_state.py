from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from codex_a2a.config import Settings
from codex_a2a.upstream.interrupts import (
    INTERRUPT_REQUEST_TOMBSTONE_TTL_SECONDS,
    InterruptRequestBinding,
)

from .database import build_database_engine
from .migrations import SchemaMigration, add_missing_columns, apply_schema_migrations

_STATE_METADATA = MetaData()
_RUNTIME_STATE_SCHEMA_SCOPE = "runtime_state"
CURRENT_RUNTIME_STATE_SCHEMA_VERSION = 2

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
}


@dataclass(frozen=True, slots=True)
class PersistedInterruptRequest:
    request_id: str
    binding: InterruptRequestBinding
    rpc_request_id: str | int
    params: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedThreadWatchOwner:
    watch_id: str
    owner_identity: str
    task_id: str
    context_id: str
    subscription_key: str
    status: str
    created_at: float
    updated_at: float
    released_at: float | None
    release_reason: str | None


@dataclass(frozen=True, slots=True)
class PersistedThreadWatchSubscription:
    subscription_key: str
    connection_scope: str
    owner_count: int
    status: str
    event_filter: tuple[str, ...] | None
    thread_filter: tuple[str, ...] | None
    created_at: float
    updated_at: float
    released_at: float | None


@dataclass(frozen=True, slots=True)
class ThreadWatchAcquireResult:
    owner: PersistedThreadWatchOwner
    subscription: PersistedThreadWatchSubscription


@dataclass(frozen=True, slots=True)
class ThreadWatchReleaseResult:
    watch_id: str
    owner_released: bool
    owner_status: str | None
    release_reason: str | None
    subscription_key: str | None
    remaining_owner_count: int | None
    subscription_released: bool


class SessionStateRepository(Protocol):
    async def load_session_binding(self, *, identity: str, context_id: str) -> str | None: ...

    async def save_session_binding(
        self,
        *,
        identity: str,
        context_id: str,
        session_id: str,
    ) -> None: ...

    async def delete_session_binding(self, *, identity: str, context_id: str) -> None: ...

    async def load_session_owner(self, *, session_id: str) -> str | None: ...

    async def save_session_owner(
        self,
        *,
        session_id: str,
        identity: str,
    ) -> None: ...

    async def load_pending_session_claim(self, *, session_id: str) -> str | None: ...

    async def save_pending_session_claim(
        self,
        *,
        session_id: str,
        identity: str,
        ttl_seconds: int,
    ) -> None: ...

    async def delete_pending_session_claim(self, *, session_id: str) -> None: ...


class InterruptRequestRepository(Protocol):
    async def save_interrupt_request(
        self,
        *,
        request_id: str,
        interrupt_type: str,
        session_id: str,
        identity: str | None,
        task_id: str | None,
        context_id: str | None,
        created_at: float,
        expires_at: float,
        rpc_request_id: str | int,
        params: dict[str, Any],
    ) -> None: ...

    async def expire_interrupt_request(self, *, request_id: str) -> None: ...

    async def resolve_interrupt_request(
        self,
        *,
        request_id: str,
    ) -> tuple[str, PersistedInterruptRequest | None]: ...

    async def delete_interrupt_request(self, *, request_id: str) -> None: ...

    async def load_interrupt_requests(self) -> list[PersistedInterruptRequest]: ...


class ThreadWatchStateRepository(Protocol):
    async def acquire_thread_watch(
        self,
        *,
        watch_id: str,
        owner_identity: str,
        task_id: str,
        context_id: str,
        subscription_key: str,
        connection_scope: str,
        event_filter: tuple[str, ...] | None,
        thread_filter: tuple[str, ...] | None,
    ) -> ThreadWatchAcquireResult: ...

    async def release_thread_watch(
        self,
        *,
        watch_id: str,
        release_reason: str,
    ) -> ThreadWatchReleaseResult: ...

    async def load_active_thread_watch_owners(self) -> list[PersistedThreadWatchOwner]: ...

    async def load_thread_watch_owner(
        self,
        *,
        watch_id: str,
    ) -> PersistedThreadWatchOwner | None: ...

    async def load_thread_watch_subscription(
        self,
        *,
        subscription_key: str,
    ) -> PersistedThreadWatchSubscription | None: ...


@dataclass(slots=True)
class RuntimeStateRuntime:
    state_store: RuntimeStateStore | None
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


async def _insert_then_update_on_conflict(
    session: AsyncSession,
    *,
    table: Table,
    key_values: Mapping[str, Any],
    update_values: Mapping[str, Any],
) -> None:
    values = {**key_values, **update_values}
    try:
        await session.execute(insert(table).values(**values))
    except IntegrityError:
        statement = update(table)
        for key, value in key_values.items():
            statement = statement.where(table.c[key] == value)
        await session.execute(statement.values(**update_values))


class RuntimeStateStore:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        interrupt_request_tombstone_ttl_seconds: float = INTERRUPT_REQUEST_TOMBSTONE_TTL_SECONDS,
    ) -> None:
        self._engine = engine
        self._session_maker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._interrupt_request_tombstone_ttl_seconds = float(
            interrupt_request_tombstone_ttl_seconds
        )
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(_STATE_METADATA.create_all)
            await conn.run_sync(self._apply_schema_migrations)
        self._initialized = True

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @staticmethod
    def _expires_at(*, ttl_seconds: int) -> float:
        return time.time() + float(ttl_seconds)

    @staticmethod
    def _apply_schema_migrations(sync_conn: Any) -> None:
        apply_schema_migrations(
            sync_conn,
            scope=_RUNTIME_STATE_SCHEMA_SCOPE,
            current_version=CURRENT_RUNTIME_STATE_SCHEMA_VERSION,
            version_table=_SCHEMA_VERSION,
            migrations=_RUNTIME_STATE_MIGRATIONS,
        )

    def _interrupt_request_tombstone_expires_at(self, *, now: float) -> float | None:
        ttl_seconds = self._interrupt_request_tombstone_ttl_seconds
        if ttl_seconds <= 0:
            return None
        return now + ttl_seconds

    async def _purge_expired_pending_claims(self, session: AsyncSession) -> None:
        now = time.time()
        await session.execute(
            delete(_PENDING_SESSION_CLAIMS).where(_PENDING_SESSION_CLAIMS.c.expires_at <= now)
        )

    async def _purge_expired_interrupt_tombstones(
        self, session: AsyncSession, *, now: float
    ) -> None:
        await session.execute(
            delete(_PENDING_INTERRUPT_REQUESTS).where(
                and_(
                    _PENDING_INTERRUPT_REQUESTS.c.tombstone_expires_at.is_not(None),
                    _PENDING_INTERRUPT_REQUESTS.c.tombstone_expires_at <= now,
                )
            )
        )

    async def _set_interrupt_request_tombstone(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        now: float,
    ) -> None:
        tombstone_expires_at = self._interrupt_request_tombstone_expires_at(now=now)
        if tombstone_expires_at is None:
            await session.execute(
                delete(_PENDING_INTERRUPT_REQUESTS).where(
                    _PENDING_INTERRUPT_REQUESTS.c.request_id == request_id
                )
            )
            return
        await session.execute(
            update(_PENDING_INTERRUPT_REQUESTS)
            .where(_PENDING_INTERRUPT_REQUESTS.c.request_id == request_id)
            .values(tombstone_expires_at=tombstone_expires_at)
        )

    @staticmethod
    def _persisted_interrupt_request_from_row(row: Any) -> PersistedInterruptRequest:
        expires_at = row.get("expires_at")
        if expires_at is None:
            expires_at = row["created_at"]
        return PersistedInterruptRequest(
            request_id=row["request_id"],
            binding=InterruptRequestBinding(
                request_id=row["request_id"],
                interrupt_type=row["interrupt_type"],
                session_id=row["session_id"],
                created_at=row["created_at"],
                expires_at=expires_at,
                identity=row.get("identity"),
                task_id=row.get("task_id"),
                context_id=row.get("context_id"),
            ),
            rpc_request_id=row["rpc_request_id"],
            params=dict(row["params"]),
        )

    @staticmethod
    def _persisted_thread_watch_owner_from_row(row: Any) -> PersistedThreadWatchOwner:
        return PersistedThreadWatchOwner(
            watch_id=row["watch_id"],
            owner_identity=row["owner_identity"],
            task_id=row["task_id"],
            context_id=row["context_id"],
            subscription_key=row["subscription_key"],
            status=row["status"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            released_at=(
                float(row["released_at"])
                if isinstance(row.get("released_at"), (float, int))
                else None
            ),
            release_reason=row.get("release_reason"),
        )

    @staticmethod
    def _normalize_json_string_tuple(value: Any) -> tuple[str, ...] | None:
        if not isinstance(value, list):
            return None
        normalized = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
        return normalized or None

    @classmethod
    def _persisted_thread_watch_subscription_from_row(
        cls,
        row: Any,
    ) -> PersistedThreadWatchSubscription:
        return PersistedThreadWatchSubscription(
            subscription_key=row["subscription_key"],
            connection_scope=row["connection_scope"],
            owner_count=int(row["owner_count"]),
            status=row["status"],
            event_filter=cls._normalize_json_string_tuple(row.get("event_filter")),
            thread_filter=cls._normalize_json_string_tuple(row.get("thread_filter")),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            released_at=(
                float(row["released_at"])
                if isinstance(row.get("released_at"), (float, int))
                else None
            ),
        )

    async def load_session_binding(self, *, identity: str, context_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            result = await session.execute(
                select(_SESSION_BINDINGS.c.session_id).where(
                    and_(
                        _SESSION_BINDINGS.c.identity == identity,
                        _SESSION_BINDINGS.c.context_id == context_id,
                    )
                )
            )
            return result.scalar_one_or_none()

    async def save_session_binding(
        self,
        *,
        identity: str,
        context_id: str,
        session_id: str,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await _insert_then_update_on_conflict(
                session,
                table=_SESSION_BINDINGS,
                key_values={
                    "identity": identity,
                    "context_id": context_id,
                },
                update_values={"session_id": session_id},
            )

    async def delete_session_binding(self, *, identity: str, context_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_SESSION_BINDINGS).where(
                    and_(
                        _SESSION_BINDINGS.c.identity == identity,
                        _SESSION_BINDINGS.c.context_id == context_id,
                    )
                )
            )

    async def load_session_owner(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            result = await session.execute(
                select(_SESSION_OWNERS.c.owner_identity).where(
                    _SESSION_OWNERS.c.session_id == session_id
                )
            )
            return result.scalar_one_or_none()

    async def save_session_owner(
        self,
        *,
        session_id: str,
        identity: str,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await _insert_then_update_on_conflict(
                session,
                table=_SESSION_OWNERS,
                key_values={"session_id": session_id},
                update_values={"owner_identity": identity},
            )

    async def load_pending_session_claim(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await self._purge_expired_pending_claims(session)
            result = await session.execute(
                select(_PENDING_SESSION_CLAIMS.c.pending_identity).where(
                    _PENDING_SESSION_CLAIMS.c.session_id == session_id
                )
            )
            return result.scalar_one_or_none()

    async def save_pending_session_claim(
        self,
        *,
        session_id: str,
        identity: str,
        ttl_seconds: int,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await _insert_then_update_on_conflict(
                session,
                table=_PENDING_SESSION_CLAIMS,
                key_values={"session_id": session_id},
                update_values={
                    "pending_identity": identity,
                    "expires_at": self._expires_at(ttl_seconds=ttl_seconds),
                },
            )

    async def delete_pending_session_claim(self, *, session_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PENDING_SESSION_CLAIMS).where(
                    _PENDING_SESSION_CLAIMS.c.session_id == session_id
                )
            )

    async def save_interrupt_request(
        self,
        *,
        request_id: str,
        interrupt_type: str,
        session_id: str,
        identity: str | None,
        task_id: str | None,
        context_id: str | None,
        created_at: float,
        expires_at: float,
        rpc_request_id: str | int,
        params: dict[str, Any],
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await _insert_then_update_on_conflict(
                session,
                table=_PENDING_INTERRUPT_REQUESTS,
                key_values={"request_id": request_id},
                update_values={
                    "interrupt_type": interrupt_type,
                    "session_id": session_id,
                    "identity": identity,
                    "task_id": task_id,
                    "context_id": context_id,
                    "created_at": created_at,
                    "expires_at": expires_at,
                    "tombstone_expires_at": None,
                    "rpc_request_id": rpc_request_id,
                    "params": params,
                },
            )

    async def expire_interrupt_request(self, *, request_id: str) -> None:
        await self._ensure_initialized()
        now = time.time()
        async with self._session_maker.begin() as session:
            await self._purge_expired_interrupt_tombstones(session, now=now)
            await self._set_interrupt_request_tombstone(session, request_id=request_id, now=now)

    async def resolve_interrupt_request(
        self,
        *,
        request_id: str,
    ) -> tuple[str, PersistedInterruptRequest | None]:
        await self._ensure_initialized()
        now = time.time()
        async with self._session_maker.begin() as session:
            await self._purge_expired_interrupt_tombstones(session, now=now)
            row = (
                (
                    await session.execute(
                        select(_PENDING_INTERRUPT_REQUESTS).where(
                            _PENDING_INTERRUPT_REQUESTS.c.request_id == request_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return "missing", None
            tombstone_expires_at = row.get("tombstone_expires_at")
            if isinstance(tombstone_expires_at, (float, int)) and tombstone_expires_at > now:
                return "expired", None
            expires_at = row.get("expires_at")
            if expires_at is None:
                expires_at = row["created_at"]
            if expires_at <= now:
                await self._set_interrupt_request_tombstone(session, request_id=request_id, now=now)
                return "expired", None
            return "active", self._persisted_interrupt_request_from_row(row)

    async def delete_interrupt_request(self, *, request_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PENDING_INTERRUPT_REQUESTS).where(
                    _PENDING_INTERRUPT_REQUESTS.c.request_id == request_id
                )
            )

    async def load_interrupt_requests(self) -> list[PersistedInterruptRequest]:
        await self._ensure_initialized()
        now = time.time()
        async with self._session_maker.begin() as session:
            await self._purge_expired_interrupt_tombstones(session, now=now)
            rows = (await session.execute(select(_PENDING_INTERRUPT_REQUESTS))).mappings().all()

            restored: list[PersistedInterruptRequest] = []
            for row in rows:
                tombstone_expires_at = row.get("tombstone_expires_at")
                if isinstance(tombstone_expires_at, (float, int)) and tombstone_expires_at > now:
                    continue
                expires_at = row.get("expires_at")
                if expires_at is None:
                    expires_at = row["created_at"]
                if expires_at <= now:
                    await self._set_interrupt_request_tombstone(
                        session,
                        request_id=row["request_id"],
                        now=now,
                    )
                    continue
                restored.append(self._persisted_interrupt_request_from_row(row))
            return restored

    async def acquire_thread_watch(
        self,
        *,
        watch_id: str,
        owner_identity: str,
        task_id: str,
        context_id: str,
        subscription_key: str,
        connection_scope: str,
        event_filter: tuple[str, ...] | None,
        thread_filter: tuple[str, ...] | None,
    ) -> ThreadWatchAcquireResult:
        await self._ensure_initialized()
        now = time.time()
        async with self._session_maker.begin() as session:
            subscription_row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_SUBSCRIPTIONS).where(
                            _THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if subscription_row is None:
                await session.execute(
                    insert(_THREAD_WATCH_SUBSCRIPTIONS).values(
                        subscription_key=subscription_key,
                        connection_scope=connection_scope,
                        owner_count=1,
                        status="active",
                        event_filter=list(event_filter) if event_filter else None,
                        thread_filter=list(thread_filter) if thread_filter else None,
                        created_at=now,
                        updated_at=now,
                        released_at=None,
                    )
                )
            else:
                owner_count = int(subscription_row["owner_count"])
                await session.execute(
                    update(_THREAD_WATCH_SUBSCRIPTIONS)
                    .where(_THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key)
                    .values(
                        connection_scope=connection_scope,
                        owner_count=owner_count + 1,
                        status="active",
                        event_filter=list(event_filter) if event_filter else None,
                        thread_filter=list(thread_filter) if thread_filter else None,
                        updated_at=now,
                        released_at=None,
                    )
                )

            await _insert_then_update_on_conflict(
                session,
                table=_THREAD_WATCH_OWNERS,
                key_values={"watch_id": watch_id},
                update_values={
                    "owner_identity": owner_identity,
                    "task_id": task_id,
                    "context_id": context_id,
                    "subscription_key": subscription_key,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                    "released_at": None,
                    "release_reason": None,
                },
            )

            owner_row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_OWNERS).where(
                            _THREAD_WATCH_OWNERS.c.watch_id == watch_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            refreshed_subscription_row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_SUBSCRIPTIONS).where(
                            _THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key
                        )
                    )
                )
                .mappings()
                .one()
            )
            return ThreadWatchAcquireResult(
                owner=self._persisted_thread_watch_owner_from_row(owner_row),
                subscription=self._persisted_thread_watch_subscription_from_row(
                    refreshed_subscription_row
                ),
            )

    async def release_thread_watch(
        self,
        *,
        watch_id: str,
        release_reason: str,
    ) -> ThreadWatchReleaseResult:
        await self._ensure_initialized()
        now = time.time()
        async with self._session_maker.begin() as session:
            owner_row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_OWNERS).where(
                            _THREAD_WATCH_OWNERS.c.watch_id == watch_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if owner_row is None:
                return ThreadWatchReleaseResult(
                    watch_id=watch_id,
                    owner_released=False,
                    owner_status=None,
                    release_reason=None,
                    subscription_key=None,
                    remaining_owner_count=None,
                    subscription_released=False,
                )

            owner_status = str(owner_row["status"])
            subscription_key = owner_row["subscription_key"]
            if owner_status != "active":
                subscription_row = (
                    (
                        await session.execute(
                            select(_THREAD_WATCH_SUBSCRIPTIONS).where(
                                _THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                remaining_owner_count = (
                    int(subscription_row["owner_count"]) if subscription_row is not None else None
                )
                subscription_released = (
                    subscription_row is not None and str(subscription_row["status"]) == "released"
                )
                return ThreadWatchReleaseResult(
                    watch_id=watch_id,
                    owner_released=False,
                    owner_status=owner_status,
                    release_reason=owner_row.get("release_reason"),
                    subscription_key=subscription_key,
                    remaining_owner_count=remaining_owner_count,
                    subscription_released=subscription_released,
                )

            next_owner_status = "orphaned" if release_reason == "restart_reconcile" else "released"
            await session.execute(
                update(_THREAD_WATCH_OWNERS)
                .where(_THREAD_WATCH_OWNERS.c.watch_id == watch_id)
                .values(
                    status=next_owner_status,
                    updated_at=now,
                    released_at=now,
                    release_reason=release_reason,
                )
            )

            subscription_row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_SUBSCRIPTIONS).where(
                            _THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if subscription_row is None:
                return ThreadWatchReleaseResult(
                    watch_id=watch_id,
                    owner_released=True,
                    owner_status=next_owner_status,
                    release_reason=release_reason,
                    subscription_key=subscription_key,
                    remaining_owner_count=0,
                    subscription_released=True,
                )

            owner_count = max(int(subscription_row["owner_count"]) - 1, 0)
            subscription_released = owner_count == 0
            await session.execute(
                update(_THREAD_WATCH_SUBSCRIPTIONS)
                .where(_THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key)
                .values(
                    owner_count=owner_count,
                    status="released" if subscription_released else "active",
                    updated_at=now,
                    released_at=now if subscription_released else None,
                )
            )
            return ThreadWatchReleaseResult(
                watch_id=watch_id,
                owner_released=True,
                owner_status=next_owner_status,
                release_reason=release_reason,
                subscription_key=subscription_key,
                remaining_owner_count=owner_count,
                subscription_released=subscription_released,
            )

    async def load_active_thread_watch_owners(self) -> list[PersistedThreadWatchOwner]:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            rows = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_OWNERS).where(
                            _THREAD_WATCH_OWNERS.c.status == "active"
                        )
                    )
                )
                .mappings()
                .all()
            )
            return [self._persisted_thread_watch_owner_from_row(row) for row in rows]

    async def load_thread_watch_owner(
        self,
        *,
        watch_id: str,
    ) -> PersistedThreadWatchOwner | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_OWNERS).where(
                            _THREAD_WATCH_OWNERS.c.watch_id == watch_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return self._persisted_thread_watch_owner_from_row(row)

    async def load_thread_watch_subscription(
        self,
        *,
        subscription_key: str,
    ) -> PersistedThreadWatchSubscription | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            row = (
                (
                    await session.execute(
                        select(_THREAD_WATCH_SUBSCRIPTIONS).where(
                            _THREAD_WATCH_SUBSCRIPTIONS.c.subscription_key == subscription_key
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            return self._persisted_thread_watch_subscription_from_row(row)


def build_runtime_state_runtime(
    settings: Settings,
    *,
    engine: AsyncEngine | None = None,
) -> RuntimeStateRuntime:
    if not settings.a2a_database_url:
        return RuntimeStateRuntime(state_store=None, startup=_noop, shutdown=_noop)

    resolved_engine = engine or build_database_engine(settings)
    state_store = RuntimeStateStore(resolved_engine)

    async def _startup() -> None:
        await state_store.initialize()

    async def _shutdown() -> None:
        if engine is None:
            await state_store.dispose()

    return RuntimeStateRuntime(
        state_store=state_store,
        startup=_startup,
        shutdown=_shutdown,
    )
