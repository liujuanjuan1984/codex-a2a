import pytest

from a2a.client import (
    A2AClientHTTPError,
    A2AClientJSONRPCError,
    A2AClientJSONError,
    A2AClientTimeoutError,
)

from codex_a2a.client.errors import (
    A2AClientProtocolError,
    A2AClientRequestError,
    map_a2a_sdk_error,
)


def test_http_error_maps_status_code() -> None:
    mapped = map_a2a_sdk_error(A2AClientHTTPError(429, "rate limited"))

    assert isinstance(mapped, A2AClientRequestError)
    assert mapped.status_code == 429


def test_timeout_error_maps_to_request_error() -> None:
    mapped = map_a2a_sdk_error(A2AClientTimeoutError("timeout"))

    assert isinstance(mapped, A2AClientRequestError)


def test_protocol_errors_map_to_protocol_error() -> None:
    assert isinstance(
        map_a2a_sdk_error(A2AClientJSONError("bad json")),
        A2AClientProtocolError,
    )
    assert isinstance(
        map_a2a_sdk_error(A2AClientJSONRPCError("bad rpc")),
        A2AClientProtocolError,
    )
