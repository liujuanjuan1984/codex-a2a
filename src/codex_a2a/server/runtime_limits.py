from __future__ import annotations

import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


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
        method == "GET" and path.startswith("/v1/tasks/") and path.endswith(":subscribe")
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
            await _send_json_error(
                scope,
                send,
                status_code=429,
                message="Runtime operation capacity is exhausted",
                headers={"Retry-After": "1"},
            )
            return

        try:
            await self.app(scope, receive, send)
        finally:
            await self.capacity.release()
