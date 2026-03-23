from __future__ import annotations

from a2a.client import (
    A2AClientHTTPError,
    A2AClientJSONError,
    A2AClientJSONRPCError,
    A2AClientTimeoutError,
)

from codex_a2a.client.errors import (
    A2AAgentUnavailableError,
    A2AClientProtocolError,
    A2AClientRequestError,
    A2AClientResetRequiredError,
    A2APeerProtocolError,
    A2AUnsupportedOperationError,
    map_a2a_sdk_error,
)


def test_http_unsupported_operation_maps_status_code() -> None:
    mapped = map_a2a_sdk_error(
        A2AClientHTTPError(405, "method unsupported"), operation="message/send"
    )

    assert isinstance(mapped, A2AUnsupportedOperationError)
    assert isinstance(mapped, A2AClientRequestError)
    assert mapped.status_code == 405


def test_http_reset_required_maps_transient_failure() -> None:
    mapped = map_a2a_sdk_error(
        A2AClientHTTPError(503, "temporary failure"), operation="message/send"
    )

    assert isinstance(mapped, A2AClientResetRequiredError)
    assert mapped.status_code == 503


def test_http_generic_failure_maps_unavailable() -> None:
    mapped = map_a2a_sdk_error(A2AClientHTTPError(5020, "weird"), operation="message/send")

    assert isinstance(mapped, A2AAgentUnavailableError)
    assert mapped.status_code == 5020


def test_timeout_maps_unavailable() -> None:
    mapped = map_a2a_sdk_error(A2AClientTimeoutError("timeout"))

    assert isinstance(mapped, A2AAgentUnavailableError)


def test_protocol_errors_map_to_protocol_type() -> None:
    assert isinstance(
        map_a2a_sdk_error(A2AClientJSONError("bad json")),
        A2AClientProtocolError,
    )
    assert isinstance(
        map_a2a_sdk_error(A2AClientJSONRPCError("bad rpc")),
        A2APeerProtocolError,
    )


def test_jsonrpc_mapping_variants(monkeypatch) -> None:
    import codex_a2a.client.errors as client_errors

    def fake_jsonrpc_payload(_: A2AClientJSONRPCError) -> tuple[str, int | None, object | None]:
        return "bad params", -32602, {"field": "message"}

    monkeypatch.setattr(client_errors, "_extract_jsonrpc_error_payload", fake_jsonrpc_payload)

    mapped = client_errors.map_a2a_sdk_error(
        A2AClientJSONRPCError("bad rpc"), operation="message/send"
    )

    assert isinstance(mapped, A2APeerProtocolError)
    assert mapped.error_code == "invalid_params"
    assert mapped.code == -32602
    assert mapped.data == {"field": "message"}
