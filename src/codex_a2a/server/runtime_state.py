from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Float, JSON, String, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from codex_a2a.config import Settings
from codex_a2a.upstream.interrupts import InterruptRequestBinding


class _Base(DeclarativeBase):
    pass


class _SessionBindingRow(_Base):
    __tablename__ = "a2a_session_bindings"

    identity: Mapped[str] = mapped_column(String, primary_key=True)
    context_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


class _SessionOwnerRow(_Base):
    __tablename__ = "a2a_session_owners"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_identity: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


class _PendingSessionClaimRow(_Base):
    __tablename__ = "a2a_pending_session_claims"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    pending_identity: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)


class _PendingInterruptRequestRow(_Base):
    __tablename__ = "a2a_pending_interrupt_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    interrupt_type: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    rpc_request_id: Mapped[str | int] = mapped_column(JSON, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


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


def _default_database_url(settings: Settings) -> str:
    base_path = (
        Path(settings.codex_workspace_root).expanduser()
        if settings.codex_workspace_root
        else Path.cwd()
    )
    db_path = (base_path / ".codex-a2a" / "tasks.db").resolve()
    return f"sqlite+aiosqlite:///{db_path}"


class RuntimeStateStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_maker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)
        self._initialized = True

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @staticmethod
    def _expires_at(*, ttl_seconds: int) -> float:
        return time.monotonic() + float(ttl_seconds)

    async def _purge_expired_session_state(self, session: AsyncSession) -> None:
        now = time.monotonic()
        await session.execute(delete(_SessionBindingRow).where(_SessionBindingRow.expires_at <= now))
        await session.execute(delete(_SessionOwnerRow).where(_SessionOwnerRow.expires_at <= now))
        await session.execute(
            delete(_PendingSessionClaimRow).where(_PendingSessionClaimRow.expires_at <= now)
        )

    async def load_session_binding(self, *, identity: str, context_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await self._purge_expired_session_state(session)
            row = await session.scalar(
                select(_SessionBindingRow).where(
                    _SessionBindingRow.identity == identity,
                    _SessionBindingRow.context_id == context_id,
                )
            )
            return row.session_id if row is not None else None

    async def save_session_binding(
        self,
        *,
        identity: str,
        context_id: str,
        session_id: str,
        ttl_seconds: int,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.merge(
                _SessionBindingRow(
                    identity=identity,
                    context_id=context_id,
                    session_id=session_id,
                    expires_at=self._expires_at(ttl_seconds=ttl_seconds),
                )
            )

    async def delete_session_binding(self, *, identity: str, context_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_SessionBindingRow).where(
                    _SessionBindingRow.identity == identity,
                    _SessionBindingRow.context_id == context_id,
                )
            )

    async def load_session_owner(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await self._purge_expired_session_state(session)
            row = await session.get(_SessionOwnerRow, session_id)
            return row.owner_identity if row is not None else None

    async def save_session_owner(
        self,
        *,
        session_id: str,
        identity: str,
        ttl_seconds: int,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.merge(
                _SessionOwnerRow(
                    session_id=session_id,
                    owner_identity=identity,
                    expires_at=self._expires_at(ttl_seconds=ttl_seconds),
                )
            )

    async def load_pending_session_claim(self, *, session_id: str) -> str | None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await self._purge_expired_session_state(session)
            row = await session.get(_PendingSessionClaimRow, session_id)
            return row.pending_identity if row is not None else None

    async def save_pending_session_claim(
        self,
        *,
        session_id: str,
        identity: str,
        ttl_seconds: int,
    ) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.merge(
                _PendingSessionClaimRow(
                    session_id=session_id,
                    pending_identity=identity,
                    expires_at=self._expires_at(ttl_seconds=ttl_seconds),
                )
            )

    async def delete_pending_session_claim(self, *, session_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PendingSessionClaimRow).where(
                    _PendingSessionClaimRow.session_id == session_id
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
        async with self._session_maker.begin() as session:
            await session.merge(
                _PendingInterruptRequestRow(
                    request_id=request_id,
                    interrupt_type=interrupt_type,
                    session_id=session_id,
                    created_at=created_at,
                    rpc_request_id=rpc_request_id,
                    params=params,
                )
            )

    async def delete_interrupt_request(self, *, request_id: str) -> None:
        await self._ensure_initialized()
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PendingInterruptRequestRow).where(
                    _PendingInterruptRequestRow.request_id == request_id
                )
            )

    async def load_interrupt_requests(
        self,
        *,
        interrupt_request_ttl_seconds: int,
    ) -> list[PersistedInterruptRequest]:
        await self._ensure_initialized()
        cutoff = time.monotonic() - float(interrupt_request_ttl_seconds)
        async with self._session_maker.begin() as session:
            await session.execute(
                delete(_PendingInterruptRequestRow).where(
                    _PendingInterruptRequestRow.created_at <= cutoff
                )
            )
            rows = (
                await session.scalars(select(_PendingInterruptRequestRow))
            ).all()

        return [
            PersistedInterruptRequest(
                request_id=row.request_id,
                binding=InterruptRequestBinding(
                    request_id=row.request_id,
                    interrupt_type=row.interrupt_type,
                    session_id=row.session_id,
                    created_at=row.created_at,
                ),
                rpc_request_id=row.rpc_request_id,
                params=dict(row.params),
            )
            for row in rows
        ]


def build_runtime_state_runtime(settings: Settings) -> RuntimeStateRuntime:
    if settings.a2a_task_store_backend == "memory":
        return RuntimeStateRuntime(state_store=None, startup=_noop, shutdown=_noop)

    database_url = settings.a2a_task_store_database_url or _default_database_url(settings)
    url = make_url(database_url)

    if url.drivername.startswith("sqlite"):
        database_path = url.database
        if database_path and database_path != ":memory:" and not database_path.startswith("file:"):
            path = Path(database_path)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        database_url,
        pool_pre_ping=not url.drivername.startswith("sqlite"),
    )
    state_store = RuntimeStateStore(engine)
    return RuntimeStateRuntime(
        state_store=state_store,
        startup=state_store.initialize,
        shutdown=state_store.dispose,
    )
