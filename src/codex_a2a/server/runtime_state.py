from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
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
CURRENT_RUNTIME_STATE_SCHEMA_VERSION = 1

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
    )
}


@dataclass(frozen=True, slots=True)
class PersistedInterruptRequest:
    request_id: str
    binding: InterruptRequestBinding
    rpc_request_id: str | int
    params: dict[str, Any]


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


@dataclass(slots=True)
class RuntimeStateRuntime:
    state_store: RuntimeStateStore | None
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


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
        values = {
            "identity": identity,
            "context_id": context_id,
            "session_id": session_id,
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(_SESSION_BINDINGS.c.session_id).where(
                    and_(
                        _SESSION_BINDINGS.c.identity == identity,
                        _SESSION_BINDINGS.c.context_id == context_id,
                    )
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(_SESSION_BINDINGS).values(**values))
            else:
                await session.execute(
                    update(_SESSION_BINDINGS)
                    .where(
                        and_(
                            _SESSION_BINDINGS.c.identity == identity,
                            _SESSION_BINDINGS.c.context_id == context_id,
                        )
                    )
                    .values(**values)
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
        values = {
            "session_id": session_id,
            "owner_identity": identity,
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(_SESSION_OWNERS.c.session_id).where(
                    _SESSION_OWNERS.c.session_id == session_id
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(_SESSION_OWNERS).values(**values))
            else:
                await session.execute(
                    update(_SESSION_OWNERS)
                    .where(_SESSION_OWNERS.c.session_id == session_id)
                    .values(**values)
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
        values = {
            "session_id": session_id,
            "pending_identity": identity,
            "expires_at": self._expires_at(ttl_seconds=ttl_seconds),
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(_PENDING_SESSION_CLAIMS.c.session_id).where(
                    _PENDING_SESSION_CLAIMS.c.session_id == session_id
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(_PENDING_SESSION_CLAIMS).values(**values))
            else:
                await session.execute(
                    update(_PENDING_SESSION_CLAIMS)
                    .where(_PENDING_SESSION_CLAIMS.c.session_id == session_id)
                    .values(**values)
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
        values = {
            "request_id": request_id,
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
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(_PENDING_INTERRUPT_REQUESTS.c.request_id).where(
                    _PENDING_INTERRUPT_REQUESTS.c.request_id == request_id
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(_PENDING_INTERRUPT_REQUESTS).values(**values))
            else:
                await session.execute(
                    update(_PENDING_INTERRUPT_REQUESTS)
                    .where(_PENDING_INTERRUPT_REQUESTS.c.request_id == request_id)
                    .values(**values)
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
