import asyncio
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from codex_a2a.metrics import (
    A2A_OPERATION_ACTIVE,
    A2A_OPERATION_REJECTED_TOTAL,
    A2A_RATE_LIMIT_REJECTED_TOTAL,
    A2A_REQUEST_BODY_REJECTED_TOTAL,
    A2A_STREAM_BUDGET_REJECTED_TOTAL,
    get_metrics_registry,
)
from codex_a2a.server.runtime_limits import (
    OperationCapacity,
    OperationCapacityMiddleware,
    RequestBodyLimitMiddleware,
    SlidingWindowRateLimiter,
    StreamBudgetExceeded,
    apply_stream_budget,
)
from tests.support.dummy_clients import DummyChatCodexClient
from tests.support.http_auth import basic_auth_header
from tests.support.settings import make_settings


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    get_metrics_registry().reset()


async def _echo_body(request: Request) -> JSONResponse:
    return JSONResponse({"size": len(await request.body())})


def _body_limited_app(max_body_bytes: int) -> Starlette:
    app = Starlette(routes=[Route("/", _echo_body, methods=["POST"])])
    app.add_middleware(RequestBodyLimitMiddleware, max_body_bytes=max_body_bytes)
    return app


@pytest.mark.asyncio
async def test_request_body_limit_accepts_body_at_limit() -> None:
    transport = httpx.ASGITransport(app=_body_limited_app(4))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=b"1234")

    assert response.status_code == 200
    assert response.json() == {"size": 4}


@pytest.mark.asyncio
async def test_request_body_limit_rejects_declared_oversized_body() -> None:
    transport = httpx.ASGITransport(app=_body_limited_app(3))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=b"1234")

    assert response.status_code == 413
    assert "3-byte limit" in response.json()["error"]
    assert get_metrics_registry().snapshot()["counters"][A2A_REQUEST_BODY_REJECTED_TOTAL] == 1


@pytest.mark.asyncio
async def test_request_body_limit_rejects_chunked_oversized_body() -> None:
    async def chunks():
        yield b"12"
        yield b"34"

    transport = httpx.ASGITransport(app=_body_limited_app(3))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/", content=chunks())

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_operation_capacity_rejects_without_queueing_and_releases_slot() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def held_operation(_request: Request) -> JSONResponse:
        entered.set()
        await release.wait()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", held_operation, methods=["POST"])])
    capacity = OperationCapacity(1)
    app.add_middleware(OperationCapacityMiddleware, capacity=capacity)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = asyncio.create_task(client.post("/", json={}))
        await asyncio.wait_for(entered.wait(), timeout=1)

        rejected = await client.post("/", json={})
        assert rejected.status_code == 429
        assert rejected.headers["retry-after"] == "1"
        assert capacity.active == 1
        snapshot = get_metrics_registry().snapshot()
        assert snapshot["counters"][A2A_OPERATION_REJECTED_TOTAL] == 1
        assert snapshot["gauges"][A2A_OPERATION_ACTIVE] == 1

        release.set()
        accepted = await first

    assert accepted.status_code == 200
    assert capacity.active == 0
    assert get_metrics_registry().snapshot()["gauges"][A2A_OPERATION_ACTIVE] == 0


@pytest.mark.asyncio
async def test_operation_capacity_does_not_block_health_checks() -> None:
    capacity = OperationCapacity(1)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/health", health)])
    app.add_middleware(OperationCapacityMiddleware, capacity=capacity)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert capacity.active == 0


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class IdleTerminatingChatClient(DummyChatCodexClient):
    """Dummy upstream client whose stream terminates like a real Codex run."""

    async def stream_events(self, stop_event=None, *, directory: str | None = None):  # noqa: ANN001
        del stop_event, directory
        yield {"type": "session.idle", "properties": {"sessionID": "ses-created-1"}}


@pytest.mark.asyncio
async def test_rate_limiter_admits_until_window_capacity() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        max_requests=3,
        window_seconds=60.0,
        clock=clock,
    )

    for _ in range(3):
        assert await limiter.check_and_record("credential:alice") is True

    assert await limiter.check_and_record("credential:alice") is False
    assert await limiter.check_and_record("credential:bob") is True
    assert await limiter.retry_after("credential:alice") == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_rate_limiter_window_slides() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        max_requests=2,
        window_seconds=10.0,
        clock=clock,
    )

    assert await limiter.check_and_record("ip:1.2.3.4") is True
    clock.advance(5.0)
    assert await limiter.check_and_record("ip:1.2.3.4") is True
    assert await limiter.check_and_record("ip:1.2.3.4") is False

    clock.advance(5.0)
    assert await limiter.check_and_record("ip:1.2.3.4") is True
    assert await limiter.retry_after("ip:1.2.3.4") == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_rate_limiter_evicts_oldest_key_when_full() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        max_requests=1,
        window_seconds=60.0,
        max_keys=2,
        clock=clock,
    )

    assert await limiter.check_and_record("ip:a") is True
    assert await limiter.check_and_record("ip:b") is True
    assert await limiter.check_and_record("ip:c") is True
    # The oldest-inserted key was evicted, so it is admitted again.
    assert await limiter.check_and_record("ip:a") is True


def test_rate_limiter_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=0, window_seconds=60.0)
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=1, window_seconds=0.0)
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0, max_keys=0)


@pytest.mark.asyncio
async def test_stream_budget_byte_limit_raises_and_closes_source() -> None:
    state = {"closed": False}

    async def tracked():
        try:
            yield "a" * 40
            yield "b" * 40
            yield "c" * 40
        finally:
            state["closed"] = True

    received = []
    with pytest.raises(StreamBudgetExceeded) as excinfo:
        async for item in apply_stream_budget(
            tracked(),
            max_bytes=50,
            max_duration_seconds=0,
            idle_timeout_seconds=0,
            size_of=len,
        ):
            received.append(item)

    assert excinfo.value.reason == "byte budget"
    assert received == ["a" * 40]
    assert state["closed"] is True
    assert get_metrics_registry().snapshot()["counters"][A2A_STREAM_BUDGET_REJECTED_TOTAL] == 1


@pytest.mark.asyncio
async def test_stream_budget_duration_limit_raises() -> None:
    clock = FakeClock()

    async def delayed():
        yield "first"
        clock.advance(30.0)
        yield "second"
        clock.advance(30.0)
        yield "third"

    received = []
    with pytest.raises(StreamBudgetExceeded) as excinfo:
        async for item in apply_stream_budget(
            delayed(),
            max_bytes=0,
            max_duration_seconds=45.0,
            idle_timeout_seconds=0,
            clock=clock,
            size_of=len,
        ):
            received.append(item)

    assert excinfo.value.reason == "duration budget"
    assert received == ["first", "second"]


@pytest.mark.asyncio
async def test_stream_budget_idle_timeout_raises() -> None:
    async def slow():
        yield "first"
        await asyncio.sleep(0.08)
        yield "second"

    received = []
    with pytest.raises(StreamBudgetExceeded) as excinfo:
        async for item in apply_stream_budget(
            slow(),
            max_bytes=0,
            max_duration_seconds=0,
            idle_timeout_seconds=0.02,
            size_of=len,
        ):
            received.append(item)

    assert excinfo.value.reason == "idle timeout"
    assert received == ["first"]


@pytest.mark.asyncio
async def test_stream_budget_within_limits_passes_through() -> None:
    async def source():
        yield "hello"
        yield "world"

    received = [
        item
        async for item in apply_stream_budget(
            source(),
            max_bytes=10_000,
            max_duration_seconds=60.0,
            idle_timeout_seconds=30.0,
            size_of=len,
        )
    ]

    assert received == ["hello", "world"]


@pytest.mark.asyncio
async def test_stream_budget_disabled_values_pass_through() -> None:
    async def source():
        for _ in range(20):
            yield "x" * 10

    received = [
        item
        async for item in apply_stream_budget(
            source(),
            max_bytes=0,
            max_duration_seconds=0,
            idle_timeout_seconds=0,
            size_of=len,
        )
    ]

    assert received == ["x" * 10] * 20


def _create_rate_limited_app(**settings_overrides: Any) -> Any:
    import codex_a2a.server.application as app_module

    return app_module.create_app(make_settings(**settings_overrides))


@pytest.mark.asyncio
async def test_rate_limit_rejects_excess_authenticated_requests(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_rate_limit_max_requests=3,
        a2a_rate_limit_window_seconds=60.0,
    )
    headers = {"Authorization": "Bearer test-token"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            response = await client.get("/health", headers=headers)
            assert response.status_code == 200
        limited = await client.get("/health", headers=headers)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json() == {"error": "Too many requests"}
    assert get_metrics_registry().snapshot()["counters"][A2A_RATE_LIMIT_REJECTED_TOTAL] == 1


@pytest.mark.asyncio
async def test_rate_limit_is_per_credential(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_basic_auth_username="operator",
        a2a_basic_auth_password="op-pass",  # pragma: allowlist secret
        a2a_rate_limit_max_requests=2,
        a2a_rate_limit_window_seconds=60.0,
    )
    bearer_headers = {"Authorization": "Bearer test-token"}
    basic_headers = basic_auth_header("operator", "op-pass")  # pragma: allowlist secret
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):
            assert (await client.get("/health", headers=bearer_headers)).status_code == 200
        assert (await client.get("/health", headers=bearer_headers)).status_code == 429
        # A different credential keeps its own bucket.
        assert (await client.get("/health", headers=basic_headers)).status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_public_card_keyed_by_peer_ip(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_rate_limit_max_requests=2,
        a2a_rate_limit_window_seconds=60.0,
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):
            assert (await client.get("/.well-known/agent-card.json")).status_code == 200
        assert (await client.get("/.well-known/agent-card.json")).status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_can_be_disabled(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_rate_limit_enabled=False,
        a2a_rate_limit_max_requests=1,
        a2a_rate_limit_window_seconds=60.0,
    )
    headers = {"Authorization": "Bearer test-token"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            assert (await client.get("/health", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_streaming_byte_budget_integration_rejects_rest_before_sse(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", IdleTerminatingChatClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_stream_max_bytes=128,
        a2a_stream_max_duration_seconds=0,
        a2a_stream_idle_timeout_seconds=0,
    )
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "message": {
            "messageId": "m-rest",
            "role": "ROLE_USER",
            "parts": [{"text": "hello from rest"}],
        }
    }
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/message:stream", headers=headers, json=payload)

    assert response.status_code == 429
    error_payload = response.json()["error"]
    assert error_payload["status"] == "RESOURCE_EXHAUSTED"
    assert error_payload["message"] == "Stream budget exceeded: byte budget"
    assert get_metrics_registry().snapshot()["counters"][A2A_STREAM_BUDGET_REJECTED_TOTAL] == 1


@pytest.mark.asyncio
async def test_streaming_byte_budget_integration_terminates_jsonrpc_sse(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", IdleTerminatingChatClient)
    app = _create_rate_limited_app(
        a2a_bearer_token="test-token",
        a2a_stream_max_bytes=128,
        a2a_stream_max_duration_seconds=0,
        a2a_stream_idle_timeout_seconds=0,
    )
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendStreamingMessage",
        "params": {
            "message": {
                "messageId": "m-rpc",
                "role": "ROLE_USER",
                "parts": [{"text": "hello from jsonrpc"}],
            }
        },
    }
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/", headers=headers, json=payload) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            body = b"".join([chunk async for chunk in resp.aiter_bytes()])

    assert b"event: error" in body
    assert b"byte budget" in body


@pytest.mark.asyncio
async def test_subscribe_missing_task_returns_not_found(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(a2a_bearer_token="test-token")
    headers = {"Authorization": "Bearer test-token"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/tasks/missing:subscribe", headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_message_stream_invalid_body_returns_bad_request(monkeypatch) -> None:
    import codex_a2a.server.application as app_module

    monkeypatch.setattr(app_module, "CodexClient", DummyChatCodexClient)
    app = _create_rate_limited_app(a2a_bearer_token="test-token")
    headers = {"Authorization": "Bearer test-token"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/message:stream", headers=headers, content=b"not-json")

    assert response.status_code == 400
