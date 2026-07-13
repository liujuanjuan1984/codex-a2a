import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from codex_a2a.metrics import (
    A2A_OPERATION_ACTIVE,
    A2A_OPERATION_REJECTED_TOTAL,
    A2A_REQUEST_BODY_REJECTED_TOTAL,
    get_metrics_registry,
)
from codex_a2a.server.runtime_limits import (
    OperationCapacity,
    OperationCapacityMiddleware,
    RequestBodyLimitMiddleware,
)


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
