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


class RuntimeStateStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_maker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(_STATE_METADATA.create_all)
        self._initialized = True

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @staticmethod
    def _expires_at(*, ttl_seconds: int) -> float:
        return time.time() + float(ttl_seconds)

    async def _purge_expired_pending_claims(self, session: AsyncSession) -> None:
        now = time.time()
        await session.execute(
            delete(_PENDING_SESSION_CLAIMS).where(_PENDING_SESSION_CLAIMS.c.expires_at <= now)
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
        created_at: float,
        rpc_request_id: str | int,
        params: dict[str, Any],
    ) -> None:
        await self._ensure_initialized()
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

    async def delete_interrupt_request(self, *, request_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PENDING_INTERRUPT_REQUESTS).where(
                    _PENDING_INTERRUPT_REQUESTS.c.request_id == request_id
                )
            )

    async def load_interrupt_requests(
        self,
        *,
        interrupt_request_ttl_seconds: int,
    ) -> list[PersistedInterruptRequest]:
        await self._ensure_initialized()
        cutoff = time.time() - float(interrupt_request_ttl_seconds)
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PENDING_INTERRUPT_REQUESTS).where(
                    _PENDING_INTERRUPT_REQUESTS.c.created_at <= cutoff
                )
            )
            rows = (await session.execute(select(_PENDING_INTERRUPT_REQUESTS))).mappings().all()

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
