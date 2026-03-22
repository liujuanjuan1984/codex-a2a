from __future__ import annotations

import pytest

from codex_a2a.client import A2AClient, A2AClientConfig


class _MockAsyncHttpClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _MockSdkClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_close_idempotent() -> None:
    http_client = _MockAsyncHttpClient()
    sdk_client = _MockSdkClient()

    client = A2AClient(
        A2AClientConfig(agent_url="https://example.org"),
        httpx_client=http_client,
    )
    client._sdk_client = sdk_client  # noqa: SLF001

    await client.close()
    await client.close()

    assert client.is_closed is True
    assert http_client.closed is True
    assert sdk_client.closed is True
