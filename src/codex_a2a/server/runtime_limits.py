from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from codex_a2a.metrics import (
    A2A_OPERATION_ACTIVE,
    A2A_OPERATION_REJECTED_TOTAL,
    A2A_REQUEST_BODY_REJECTED_TOTAL,
    A2A_STREAM_BUDGET_REJECTED_TOTAL,
    get_metrics_registry,
)

RATE_LIMIT_ERROR_MESSAGE = "Too many requests"
STREAM_BUDGET_ERROR_MESSAGE = "Stream budget exceeded"
_DEFAULT_MAX_RATE_LIMIT_KEYS = 100_000
# Approximate SSE framing overhead per event: ``data: `` prefix, line
# separators, and the compact-JSON slack.
_SSE_EVENT_FRAMING_OVERHEAD = 32


def build_rate_limit_response(retry_after_seconds: float) -> JSONResponse:
    """Build a 429 response carrying a client-safe Retry-After hint."""
    retry_after = max(1, math.ceil(retry_after_seconds))
    return JSONResponse(
        {"error": RATE_LIMIT_ERROR_MESSAGE},
        status_code=429,
        headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
    )


class SlidingWindowRateLimiter:
    """Process-local sliding-window rate limiter.

    Every key tracks the timestamps of admitted requests inside the window.
    Buckets are pruned lazily on access and the key table is capped so memory
    stays bounded even under a flood of distinct keys. All mutations are
    serialized by an asyncio lock so concurrent request handlers observe a
    consistent counter.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        max_keys: int = _DEFAULT_MAX_RATE_LIMIT_KEYS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")
        if max_keys <= 0:
            raise ValueError("max_keys must be greater than 0")
        self._max_requests = max_requests
        self._window_seconds = float(window_seconds)
        self._max_keys = max_keys
        self._clock = clock or time.monotonic
        self._entries: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check_and_record(self, key: str) -> bool:
        """Return True when the request is admitted and record it."""
        async with self._lock:
            now = self._clock()
            entries = self._entries.setdefault(key, deque())
            self._prune(entries, now)
            if len(entries) >= self._max_requests:
                return False
            entries.append(now)
            self._evict_if_needed()
            return True

    async def retry_after(self, key: str) -> float:
        """Return the seconds until the oldest recorded request expires."""
        async with self._lock:
            entries = self._entries.get(key)
            if not entries:
                return self._window_seconds
            now = self._clock()
            self._prune(entries, now)
            if not entries:
                return self._window_seconds
            return max(0.0, entries[0] + self._window_seconds - now)

    def _prune(self, entries: deque[float], now: float) -> None:
        while entries and now - entries[0] >= self._window_seconds:
            entries.popleft()

    def _evict_if_needed(self) -> None:
        if len(self._entries) <= self._max_keys:
            return
        # dict preserves insertion order; evict the oldest-inserted key.
        stale_key = next(iter(self._entries))
        del self._entries[stale_key]


class StreamBudgetExceeded(Exception):
    """Raised when a streaming response exceeds its configured budget."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{STREAM_BUDGET_ERROR_MESSAGE}: {reason}")
        self.reason = reason


def json_event_size(item: Any) -> int:
    """Approximate the on-wire SSE bytes for one serialized event item."""
    serialized = json.dumps(
        item,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return len(serialized) + _SSE_EVENT_FRAMING_OVERHEAD


async def apply_stream_budget(
    stream: AsyncIterator[Any],
    *,
    max_bytes: int,
    max_duration_seconds: float,
    idle_timeout_seconds: float,
    clock: Callable[[], float] | None = None,
    size_of: Callable[[Any], int] = json_event_size,
) -> AsyncGenerator[Any, None]:
    """Yield events while enforcing byte, duration, and idle budgets.

    A value of ``0`` disables the corresponding budget. When a budget is
    exceeded ``StreamBudgetExceeded`` is raised and the underlying stream is
    closed first, so the application runs the same cleanup/drain path as a
    client disconnect and the transport emits a well-formed SSE ``error``
    event before ending the response normally.
    """
    resolve_clock = clock or time.monotonic
    started_at: float | None = None
    total_bytes = 0

    try:
        while True:
            try:
                if idle_timeout_seconds > 0:
                    event = await asyncio.wait_for(
                        anext(stream),
                        timeout=idle_timeout_seconds,
                    )
                else:
                    event = await anext(stream)
            except StopAsyncIteration:
                return
            except TimeoutError:
                _reject_budget("idle timeout")
                return

            now = resolve_clock()
            if started_at is None:
                started_at = now
            elif max_duration_seconds > 0 and now - started_at >= max_duration_seconds:
                _reject_budget("duration budget")
                return

            total_bytes += size_of(event)
            if max_bytes > 0 and total_bytes > max_bytes:
                _reject_budget("byte budget")
                return

            yield event
    finally:
        # Close the inner generator so its handler observes GeneratorExit and
        # runs the normal disconnect/drain cleanup.
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


def _reject_budget(reason: str) -> None:
    get_metrics_registry().inc_counter(A2A_STREAM_BUDGET_REJECTED_TOTAL)
    raise StreamBudgetExceeded(reason)


async def _send_json_error(
    scope: Scope,
    send: Send,
    *,
    status_code: int,
    message: str,
    headers: dict[str, str] | None = None,
) -> None:
    response = JSONResponse(
        {"error": message},
        status_code=status_code,
        headers=headers,
    )
    await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before application parsing."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in {"POST", "PUT", "PATCH"}
            or self.max_body_bytes <= 0
        ):
            await self.app(scope, receive, send)
            return

        declared_length = _content_length(scope)
        if declared_length is not None and declared_length > self.max_body_bytes:
            await self._reject(scope, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_body_bytes:
                await self._reject(scope, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        get_metrics_registry().inc_counter(A2A_REQUEST_BODY_REJECTED_TOTAL)
        await _send_json_error(
            scope,
            send,
            status_code=413,
            message=f"Request body exceeds the configured {self.max_body_bytes}-byte limit",
        )


class OperationCapacity:
    """Non-blocking process-local admission counter for long-lived requests."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._active = 0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> int:
        return self._active

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self.limit > 0 and self._active >= self.limit:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)


def _is_capacity_managed_request(scope: Scope) -> bool:
    method = scope.get("method", "")
    path = scope.get("path", "")
    return method == "POST" or (
        method == "GET" and path.startswith("/tasks/") and path.endswith(":subscribe")
    )


class OperationCapacityMiddleware:
    """Limit active operational requests without queueing unbounded work."""

    def __init__(self, app: ASGIApp, *, capacity: OperationCapacity) -> None:
        self.app = app
        self.capacity = capacity

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.capacity.limit <= 0
            or not _is_capacity_managed_request(scope)
        ):
            await self.app(scope, receive, send)
            return

        if not await self.capacity.try_acquire():
            get_metrics_registry().inc_counter(A2A_OPERATION_REJECTED_TOTAL)
            await _send_json_error(
                scope,
                send,
                status_code=429,
                message="Runtime operation capacity is exhausted",
                headers={"Retry-After": "1"},
            )
            return

        get_metrics_registry().inc_gauge(A2A_OPERATION_ACTIVE)
        try:
            await self.app(scope, receive, send)
        finally:
            await self.capacity.release()
            get_metrics_registry().dec_gauge(A2A_OPERATION_ACTIVE)
