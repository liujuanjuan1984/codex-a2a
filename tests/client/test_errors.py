from __future__ import annotations

import httpx
from a2a.client import A2AClientError as SDKA2AClientError
from a2a.client.errors import A2AClientTimeoutError, AgentCardResolutionError

from codex_a2a.client.errors import (
    A2AAgentUnavailableError,
    A2AClientProtocolError,
    A2AClientRequestError,
    A2AClientResetRequiredError,
    A2AUnsupportedOperationError,
    map_a2a_sdk_error,
)


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.org")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(f"status={status_code}", request=request, response=response)


def test_agent_card_resolution_unsupported_operation_maps_status_code() -> None:
    mapped = map_a2a_sdk_error(
        AgentCardResolutionError("method unsupported", status_code=405),
        operation="message/send",
    )

    assert isinstance(mapped, A2AUnsupportedOperationError)
    assert isinstance(mapped, A2AClientRequestError)
    assert mapped.status_code == 405
    assert mapped.code == 405


def test_http_reset_required_maps_transient_failure() -> None:
    mapped = map_a2a_sdk_error(
        _make_http_status_error(503),
        operation="message/send",
    )

    assert isinstance(mapped, A2AClientResetRequiredError)
    assert mapped.status_code == 503


def test_http_generic_failure_maps_unavailable() -> None:
    mapped = map_a2a_sdk_error(_make_http_status_error(418), operation="message/send")

    assert isinstance(mapped, A2AAgentUnavailableError)
    assert mapped.status_code == 418


def test_http_transport_error_maps_unavailable() -> None:
    mapped = map_a2a_sdk_error(httpx.ConnectError("boom"))

    assert isinstance(mapped, A2AAgentUnavailableError)


def test_timeout_maps_unavailable() -> None:
    mapped = map_a2a_sdk_error(A2AClientTimeoutError("timeout"))

    assert isinstance(mapped, A2AAgentUnavailableError)


def test_sdk_protocol_errors_map_to_protocol_type() -> None:
    mapped = map_a2a_sdk_error(SDKA2AClientError("bad payload"))

    assert isinstance(mapped, A2AClientProtocolError)
