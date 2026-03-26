from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Float,
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
from codex_a2a.upstream.interrupts import InterruptRequestBinding

from .database import build_database_engine

_STATE_METADATA = MetaData()

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
    Column("created_at", Float, nullable=False),
    Column("rpc_request_id", JSON, nullable=False),
    Column("params", JSON, nullable=False),
)

_TABLE_NAMES = (
    "a2a_session_bindings",
    "a2a_session_owners",
    "a2a_pending_session_claims",
    "a2a_pending_interrupt_requests",
)


@dataclass(frozen=True, slots=True)
class PersistedInterruptRequest:
    request_id: str
    binding: InterruptRequestBinding
    rpc_request_id: str | int
    params: dict[str, Any]


@dataclass(slots=True)
class RuntimeStateRuntime:
    state_store: RuntimeStateStore | None
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


async def _noop() -> None:
    return None


_LEGACY_PERSISTED_STATE_EXPIRES_AT = 4_102_444_800.0


class RuntimeStateStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_maker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._initialized = False
        self._tables: dict[str, Table] = {}

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(_STATE_METADATA.create_all)
            await conn.run_sync(self._reflect_tables)
        self._initialized = True

    def _reflect_tables(self, sync_conn) -> None:  # noqa: ANN001
        reflected = MetaData()
        reflected.reflect(bind=sync_conn, only=list(_TABLE_NAMES))
        self._tables = {name: reflected.tables[name] for name in _TABLE_NAMES}

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    def _table(self, name: str) -> Table:
        table = self._tables.get(name)
        if table is None:
            raise RuntimeError(f"Runtime state table {name} not initialized")
        return table

    @staticmethod
    def _expires_at(*, ttl_seconds: int) -> float:
        return time.time() + float(ttl_seconds)

    @staticmethod
    def _legacy_compatible_values(table: Table, values: dict[str, Any]) -> dict[str, Any]:
        if "expires_at" in table.c and "expires_at" not in values:
            return {**values, "expires_at": _LEGACY_PERSISTED_STATE_EXPIRES_AT}
        return values

    async def _purge_expired_pending_claims(self, session: AsyncSession) -> None:
        pending_claims = self._table("a2a_pending_session_claims")
        now = time.time()
        await session.execute(delete(pending_claims).where(pending_claims.c.expires_at <= now))

    async def load_session_binding(self, *, identity: str, context_id: str) -> str | None:
        await self._ensure_initialized()
        bindings = self._table("a2a_session_bindings")
        async with self._session_maker.begin() as session:
            result = await session.execute(
                select(bindings.c.session_id).where(
                    and_(
                        bindings.c.identity == identity,
                        bindings.c.context_id == context_id,
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
        bindings = self._table("a2a_session_bindings")
        values = self._legacy_compatible_values(
            bindings,
            {
                "identity": identity,
                "context_id": context_id,
                "session_id": session_id,
            },
        )
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(bindings.c.session_id).where(
                    and_(
                        bindings.c.identity == identity,
                        bindings.c.context_id == context_id,
                    )
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(bindings).values(**values))
            else:
                await session.execute(
                    update(bindings)
                    .where(
                        and_(
                            bindings.c.identity == identity,
                            bindings.c.context_id == context_id,
                        )
                    )
                    .values(**values)
                )

    async def delete_session_binding(self, *, identity: str, context_id: str) -> None:
        await self._ensure_initialized()
        bindings = self._table("a2a_session_bindings")
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(bindings).where(
                    and_(
                        bindings.c.identity == identity,
                        bindings.c.context_id == context_id,
                    )
                )
            )

    async def load_session_owner(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        owners = self._table("a2a_session_owners")
        async with self._session_maker.begin() as session:
            result = await session.execute(
                select(owners.c.owner_identity).where(owners.c.session_id == session_id)
            )
            return result.scalar_one_or_none()

    async def save_session_owner(
        self,
        *,
        session_id: str,
        identity: str,
    ) -> None:
        await self._ensure_initialized()
        owners = self._table("a2a_session_owners")
        values = self._legacy_compatible_values(
            owners,
            {
                "session_id": session_id,
                "owner_identity": identity,
            },
        )
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(owners.c.session_id).where(owners.c.session_id == session_id)
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(owners).values(**values))
            else:
                await session.execute(
                    update(owners).where(owners.c.session_id == session_id).values(**values)
                )

    async def load_pending_session_claim(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        pending_claims = self._table("a2a_pending_session_claims")
        async with self._session_maker.begin() as session:
            await self._purge_expired_pending_claims(session)
            result = await session.execute(
                select(pending_claims.c.pending_identity).where(
                    pending_claims.c.session_id == session_id
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
        pending_claims = self._table("a2a_pending_session_claims")
        values = {
            "session_id": session_id,
            "pending_identity": identity,
            "expires_at": self._expires_at(ttl_seconds=ttl_seconds),
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(pending_claims.c.session_id).where(pending_claims.c.session_id == session_id)
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(pending_claims).values(**values))
            else:
                await session.execute(
                    update(pending_claims)
                    .where(pending_claims.c.session_id == session_id)
                    .values(**values)
                )

    async def delete_pending_session_claim(self, *, session_id: str) -> None:
        await self._ensure_initialized()
        pending_claims = self._table("a2a_pending_session_claims")
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(pending_claims).where(pending_claims.c.session_id == session_id)
            )

    async def save_interrupt_request(
        self,
        *,
        request_id: str,
        interrupt_type: str,
        session_id: str,
        created_at: float,
        rpc_request_id: str | int,
        params: dict[str, Any],
    ) -> None:
        await self._ensure_initialized()
        interrupt_requests = self._table("a2a_pending_interrupt_requests")
        values = {
            "request_id": request_id,
            "interrupt_type": interrupt_type,
            "session_id": session_id,
            "created_at": created_at,
            "rpc_request_id": rpc_request_id,
            "params": params,
        }
        async with self._session_maker.begin() as session:
            existing = await session.execute(
                select(interrupt_requests.c.request_id).where(
                    interrupt_requests.c.request_id == request_id
                )
            )
            if existing.scalar_one_or_none() is None:
                await session.execute(insert(interrupt_requests).values(**values))
            else:
                await session.execute(
                    update(interrupt_requests)
                    .where(interrupt_requests.c.request_id == request_id)
                    .values(**values)
                )

    async def delete_interrupt_request(self, *, request_id: str) -> None:
        await self._ensure_initialized()
        interrupt_requests = self._table("a2a_pending_interrupt_requests")
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(interrupt_requests).where(interrupt_requests.c.request_id == request_id)
            )

    async def load_interrupt_requests(
        self,
        *,
        interrupt_request_ttl_seconds: int,
    ) -> list[PersistedInterruptRequest]:
        await self._ensure_initialized()
        interrupt_requests = self._table("a2a_pending_interrupt_requests")
        cutoff = time.time() - float(interrupt_request_ttl_seconds)
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(interrupt_requests).where(interrupt_requests.c.created_at <= cutoff)
            )
            rows = (await session.execute(select(interrupt_requests))).mappings().all()

        return [
            PersistedInterruptRequest(
                request_id=row["request_id"],
                binding=InterruptRequestBinding(
                    request_id=row["request_id"],
                    interrupt_type=row["interrupt_type"],
                    session_id=row["session_id"],
                    created_at=row["created_at"],
                ),
                rpc_request_id=row["rpc_request_id"],
                params=dict(row["params"]),
            )
            for row in rows
        ]


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
