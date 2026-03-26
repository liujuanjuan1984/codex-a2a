from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codex_a2a.server.runtime_state import RuntimeStateStore


class TTLCache:
    """Bounded TTL cache for hashable key -> string value."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        maxsize: int,
        now: Callable[[], float] = time.monotonic,
        refresh_on_get: bool = False,
    ) -> None:
        self._ttl_seconds = int(ttl_seconds)
        self._maxsize = int(maxsize)
        self._now = now
        self._refresh_on_get = bool(refresh_on_get)
        self._store: dict[object, tuple[str, float]] = {}

    def get(self, key: object) -> str | None:
        if self._ttl_seconds <= 0 or self._maxsize <= 0:
            return None
        item = self._store.get(key)
        if not item:
            return None
        value, expires_at = item
        now = self._now()
        if expires_at <= now:
            self._store.pop(key, None)
            return None
        if self._refresh_on_get:
            self._store[key] = (value, now + float(self._ttl_seconds))
        return value

    def set(self, key: object, value: str) -> None:
        if self._ttl_seconds <= 0 or self._maxsize <= 0:
            return
        now = self._now()
        self._store[key] = (value, now + float(self._ttl_seconds))
        self._evict_if_needed(now=now)

    def pop(self, key: object) -> None:
        self._store.pop(key, None)

    def _evict_if_needed(self, *, now: float) -> None:
        if len(self._store) <= self._maxsize:
            return
        expired = [key for key, (_, expires_at) in self._store.items() if expires_at <= now]
        for key in expired:
            self._store.pop(key, None)
        if len(self._store) <= self._maxsize:
            return
        overflow = len(self._store) - self._maxsize
        by_expiry = sorted(self._store.items(), key=lambda item: item[1][1])
        for key, _ in by_expiry[:overflow]:
            self._store.pop(key, None)


@dataclass(frozen=True)
class RunningExecutionSnapshot:
    identity: str
    task: asyncio.Task[Any] | None
    stop_event: asyncio.Event | None
    inflight_create: asyncio.Task[str] | None


@dataclass(frozen=True)
class SessionClaimSnapshot:
    session_id: str
    owner_identity: str | None
    pending_identity: str | None


@dataclass(frozen=True)
class SessionBindingSnapshot:
    identity: str
    context_id: str
    session_id: str | None
    owner_identity: str | None
    pending_identity: str | None


class SessionRuntime:
    def __init__(
        self,
        *,
        session_cache_ttl_seconds: int,
        session_cache_maxsize: int,
        state_store: RuntimeStateStore | None = None,
    ) -> None:
        self._session_cache_ttl_seconds = int(session_cache_ttl_seconds)
        self._sessions = TTLCache(
            ttl_seconds=session_cache_ttl_seconds,
            maxsize=session_cache_maxsize,
        )
        self._session_owners = TTLCache(
            ttl_seconds=session_cache_ttl_seconds,
            maxsize=session_cache_maxsize,
            refresh_on_get=True,
        )
        self._pending_session_claims: dict[str, str] = {}
        self._inflight_session_creates: dict[tuple[str, str], asyncio.Task[str]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._running_requests: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._running_stop_events: dict[tuple[str, str], asyncio.Event] = {}
        self._running_identities: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()
        self._state_store = state_store

    async def _load_bound_session(self, *, identity: str, context_id: str) -> str | None:
        existing = self._sessions.get((identity, context_id))
        if existing is not None or self._state_store is None:
            return existing
        restored = await self._state_store.load_session_binding(
            identity=identity, context_id=context_id
        )
        if restored is not None:
            self._sessions.set((identity, context_id), restored)
        return restored

    async def _persist_bound_session(
        self,
        *,
        identity: str,
        context_id: str,
        session_id: str,
    ) -> None:
        self._sessions.set((identity, context_id), session_id)
        if self._state_store is not None:
            await self._state_store.save_session_binding(
                identity=identity,
                context_id=context_id,
                session_id=session_id,
                ttl_seconds=self._session_cache_ttl_seconds,
            )

    async def _delete_bound_session(self, *, identity: str, context_id: str) -> None:
        self._sessions.pop((identity, context_id))
        if self._state_store is not None:
            await self._state_store.delete_session_binding(identity=identity, context_id=context_id)

    async def _load_session_owner(self, *, session_id: str) -> str | None:
        owner = self._session_owners.get(session_id)
        if owner is not None or self._state_store is None:
            return owner
        restored = await self._state_store.load_session_owner(session_id=session_id)
        if restored is not None:
            self._session_owners.set(session_id, restored)
        return restored

    async def _persist_session_owner(self, *, session_id: str, identity: str) -> None:
        self._session_owners.set(session_id, identity)
        if self._state_store is not None:
            await self._state_store.save_session_owner(
                session_id=session_id,
                identity=identity,
                ttl_seconds=self._session_cache_ttl_seconds,
            )

    async def _load_pending_claim(self, *, session_id: str) -> str | None:
        pending = self._pending_session_claims.get(session_id)
        if pending is not None or self._state_store is None:
            return pending
        restored = await self._state_store.load_pending_session_claim(session_id=session_id)
        if restored is not None:
            self._pending_session_claims[session_id] = restored
        return restored

    async def _persist_pending_claim(self, *, session_id: str, identity: str) -> None:
        self._pending_session_claims[session_id] = identity
        if self._state_store is not None:
            await self._state_store.save_pending_session_claim(
                session_id=session_id,
                identity=identity,
                ttl_seconds=self._session_cache_ttl_seconds,
            )

    async def _delete_pending_claim(self, *, session_id: str) -> None:
        self._pending_session_claims.pop(session_id, None)
        if self._state_store is not None:
            await self._state_store.delete_pending_session_claim(session_id=session_id)

    async def bound_session_for(self, *, identity: str, context_id: str) -> str | None:
        async with self._lock:
            return await self._load_bound_session(identity=identity, context_id=context_id)

    async def binding_snapshot(
        self,
        *,
        identity: str,
        context_id: str,
    ) -> SessionBindingSnapshot:
        async with self._lock:
            session_id = await self._load_bound_session(identity=identity, context_id=context_id)
            owner_identity = (
                await self._load_session_owner(session_id=session_id) if session_id else None
            )
            pending_identity = (
                await self._load_pending_claim(session_id=session_id) if session_id else None
            )
        return SessionBindingSnapshot(
            identity=identity,
            context_id=context_id,
            session_id=session_id,
            owner_identity=owner_identity,
            pending_identity=pending_identity,
        )

    async def session_claim_snapshot(self, *, session_id: str) -> SessionClaimSnapshot:
        async with self._lock:
            owner_identity = await self._load_session_owner(session_id=session_id)
            pending_identity = await self._load_pending_claim(session_id=session_id)
        return SessionClaimSnapshot(
            session_id=session_id,
            owner_identity=owner_identity,
            pending_identity=pending_identity,
        )

    async def running_execution_snapshot(
        self,
        *,
        task_id: str,
        context_id: str,
    ) -> RunningExecutionSnapshot | None:
        execution_key = (task_id, context_id)
        async with self._lock:
            identity = self._running_identities.get(execution_key)
            task = self._running_requests.get(execution_key)
            stop_event = self._running_stop_events.get(execution_key)
            if identity is None and task is None and stop_event is None:
                return None
            inflight_create = (
                self._inflight_session_creates.get((identity, context_id))
                if identity is not None
                else None
            )
        return RunningExecutionSnapshot(
            identity=identity or "",
            task=task,
            stop_event=stop_event,
            inflight_create=inflight_create,
        )

    async def track_running_request(
        self,
        *,
        task_id: str,
        context_id: str,
        identity: str,
        task: asyncio.Task[Any],
        stop_event: asyncio.Event,
    ) -> None:
        execution_key = (task_id, context_id)
        async with self._lock:
            self._running_requests[execution_key] = task
            self._running_stop_events[execution_key] = stop_event
            self._running_identities[execution_key] = identity

    async def untrack_running_request(self, *, task_id: str, context_id: str) -> None:
        execution_key = (task_id, context_id)
        async with self._lock:
            self._running_requests.pop(execution_key, None)
            self._running_stop_events.pop(execution_key, None)
            self._running_identities.pop(execution_key, None)

    async def cancel_running_request(
        self,
        *,
        task_id: str,
        context_id: str,
        identity: str,
    ) -> RunningExecutionSnapshot:
        execution_key = (task_id, context_id)
        async with self._lock:
            running_identity = self._running_identities.get(execution_key, identity)
            running_task = self._running_requests.get(execution_key)
            stop_event = self._running_stop_events.get(execution_key)
            await self._delete_bound_session(identity=running_identity, context_id=context_id)
            inflight_create = self._inflight_session_creates.pop(
                (running_identity, context_id),
                None,
            )
        return RunningExecutionSnapshot(
            identity=running_identity,
            task=running_task,
            stop_event=stop_event,
            inflight_create=inflight_create,
        )

    async def get_or_create_session(
        self,
        *,
        identity: str,
        context_id: str,
        title: str,
        preferred_session_id: str | None,
        create_session: Callable[[], Coroutine[object, object, str]],
    ) -> tuple[str, bool]:
        if preferred_session_id:
            async with self._lock:
                owner = await self._load_session_owner(session_id=preferred_session_id)
                pending_owner = await self._load_pending_claim(session_id=preferred_session_id)
                self._assert_claimable_session(
                    session_id=preferred_session_id,
                    identity=identity,
                    owner=owner,
                    pending_owner=pending_owner,
                )
                if owner == identity:
                    await self._persist_bound_session(
                        identity=identity,
                        context_id=context_id,
                        session_id=preferred_session_id,
                    )
                    return preferred_session_id, False

                await self._persist_pending_claim(
                    session_id=preferred_session_id, identity=identity
                )
                return preferred_session_id, True

        cache_key = (identity, context_id)
        async with self._lock:
            existing = await self._load_bound_session(
                identity=identity,
                context_id=context_id,
            )
            if existing:
                return existing, False
            task = self._inflight_session_creates.get(cache_key)
            if task is None:
                task = asyncio.create_task(create_session())
                self._inflight_session_creates[cache_key] = task

        try:
            session_id = await task
        except Exception:
            async with self._lock:
                if self._inflight_session_creates.get(cache_key) is task:
                    self._inflight_session_creates.pop(cache_key, None)
            raise

        async with self._lock:
            owner = await self._load_session_owner(session_id=session_id)
            self._assert_claimable_session(
                session_id=session_id,
                identity=identity,
                owner=owner,
                pending_owner=None,
            )
            await self._persist_bound_session(
                identity=identity,
                context_id=context_id,
                session_id=session_id,
            )
            if not owner:
                await self._persist_session_owner(session_id=session_id, identity=identity)
            if self._inflight_session_creates.get(cache_key) is task:
                self._inflight_session_creates.pop(cache_key, None)
        return session_id, False

    async def finalize_preferred_session_binding(
        self,
        *,
        identity: str,
        context_id: str,
        session_id: str,
    ) -> None:
        async with self._lock:
            owner = await self._load_session_owner(session_id=session_id)
            pending_owner = await self._load_pending_claim(session_id=session_id)
            self._assert_claimable_session(
                session_id=session_id,
                identity=identity,
                owner=owner,
                pending_owner=pending_owner,
            )
            await self._persist_session_owner(session_id=session_id, identity=identity)
            await self._persist_bound_session(
                identity=identity,
                context_id=context_id,
                session_id=session_id,
            )
            if pending_owner == identity:
                await self._delete_pending_claim(session_id=session_id)

    async def release_preferred_session_claim(self, *, identity: str, session_id: str) -> None:
        async with self._lock:
            if await self._load_pending_claim(session_id=session_id) == identity:
                await self._delete_pending_claim(session_id=session_id)

    async def claim_session(self, *, identity: str, session_id: str) -> bool:
        async with self._lock:
            owner = await self._load_session_owner(session_id=session_id)
            pending_owner = await self._load_pending_claim(session_id=session_id)
            self._assert_claimable_session(
                session_id=session_id,
                identity=identity,
                owner=owner,
                pending_owner=pending_owner,
            )
            if owner == identity:
                return False
            await self._persist_pending_claim(session_id=session_id, identity=identity)
            return True

    async def finalize_session_claim(self, *, identity: str, session_id: str) -> None:
        async with self._lock:
            owner = await self._load_session_owner(session_id=session_id)
            pending_owner = await self._load_pending_claim(session_id=session_id)
            self._assert_claimable_session(
                session_id=session_id,
                identity=identity,
                owner=owner,
                pending_owner=pending_owner,
            )
            await self._persist_session_owner(session_id=session_id, identity=identity)
            if pending_owner == identity:
                await self._delete_pending_claim(session_id=session_id)

    async def release_session_claim(self, *, identity: str, session_id: str) -> None:
        await self.release_preferred_session_claim(identity=identity, session_id=session_id)

    async def session_owner_matches(self, *, identity: str, session_id: str) -> bool | None:
        async with self._lock:
            owner = await self._load_session_owner(session_id=session_id)
            if owner:
                return owner == identity
            pending_owner = await self._load_pending_claim(session_id=session_id)
            if pending_owner:
                return pending_owner == identity
        return None

    async def get_session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

    def _assert_claimable_session(
        self,
        *,
        session_id: str,
        identity: str,
        owner: str | None,
        pending_owner: str | None,
    ) -> None:
        if owner and owner != identity:
            raise PermissionError(f"Session {session_id} is not owned by you")
        if pending_owner and pending_owner != identity:
            raise PermissionError(f"Session {session_id} is not owned by you")
