from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_a2a.client.config import A2AClientConfig
from codex_a2a.client.request_context import (
    build_call_context,
    build_default_headers,
    split_request_metadata,
)
from codex_a2a.contracts.extensions import SESSION_BINDING_EXTENSION_URI, STREAMING_EXTENSION_URI


def test_split_request_metadata_separates_authorization_header() -> None:
    request_metadata, extra_headers, requested_extensions = split_request_metadata(
        {"authorization": "Bearer explicit-token", "trace_id": "trace-1"}
    )

    assert request_metadata == {"trace_id": "trace-1"}
    assert extra_headers == {"Authorization": "Bearer explicit-token"}
    assert requested_extensions is None


def test_split_request_metadata_rejects_non_string_authorization_header() -> None:
    with pytest.raises(ValueError, match="Authorization metadata header must be a string"):
        split_request_metadata({"authorization": 123})


def test_split_request_metadata_rejects_protocol_version_override() -> None:
    with pytest.raises(ValueError, match="A2A-Version is fixed to 1.0"):
        split_request_metadata({"a2a-version": "1.0"})


def test_split_request_metadata_extracts_a2a_extensions_header() -> None:
    request_metadata, extra_headers, requested_extensions = split_request_metadata(
        {
            "a2a-extensions": [
                SESSION_BINDING_EXTENSION_URI,
                f"{STREAMING_EXTENSION_URI}, {SESSION_BINDING_EXTENSION_URI}",
            ],
            "trace_id": "trace-1",
        }
    )

    assert request_metadata == {"trace_id": "trace-1"}
    assert extra_headers is None
    assert requested_extensions == (
        SESSION_BINDING_EXTENSION_URI,
        STREAMING_EXTENSION_URI,
    )


def test_split_request_metadata_ignores_empty_input() -> None:
    request_metadata, extra_headers, requested_extensions = split_request_metadata(None)

    assert request_metadata is None
    assert extra_headers is None
    assert requested_extensions is None


def test_build_call_context_carries_headers_via_service_parameters() -> None:
    context = build_call_context({"Authorization": "Bearer explicit-token"})

    assert context is not None
    assert context.service_parameters == {"Authorization": "Bearer explicit-token"}


def test_client_config_canonicalizes_fixed_protocol_version_header() -> None:
    config = A2AClientConfig(
        agent_url="https://example.org",
        default_headers={"a2a-version": "1.0", "X-Trace-Id": "trace-1"},
    )

    assert config.default_headers == {
        "A2A-Version": "1.0",
        "X-Trace-Id": "trace-1",
    }


def test_client_config_rejects_protocol_version_override() -> None:
    with pytest.raises(ValidationError, match="A2A-Version is fixed to 1.0"):
        A2AClientConfig(
            agent_url="https://example.org",
            default_headers={"A2A-Version": "0.3"},
        )


def test_build_call_context_merges_extensions_into_service_parameters() -> None:
    context = build_call_context(
        {"Authorization": "Bearer explicit-token"},
        (SESSION_BINDING_EXTENSION_URI, STREAMING_EXTENSION_URI),
    )

    assert context is not None
    assert context.service_parameters == {
        "Authorization": "Bearer explicit-token",
        "A2A-Extensions": (f"{SESSION_BINDING_EXTENSION_URI},{STREAMING_EXTENSION_URI}"),
    }


def test_build_call_context_merges_defaults_before_explicit_headers() -> None:
    context = build_call_context(
        {"Authorization": "Bearer explicit-token"},
        default_headers={
            "A2A-Version": "1.0",
            "Authorization": "Bearer default-token",
        },
    )

    assert context is not None
    assert context.service_parameters == {
        "A2A-Version": "1.0",
        "Authorization": "Bearer explicit-token",
    }


def test_build_call_context_returns_none_without_headers() -> None:
    assert build_call_context(None) is None


def test_build_call_context_returns_extensions_without_headers() -> None:
    context = build_call_context(None, (SESSION_BINDING_EXTENSION_URI,))

    assert context is not None
    assert context.service_parameters == {
        "A2A-Extensions": SESSION_BINDING_EXTENSION_URI,
    }


def test_build_default_headers_prefers_bearer_over_basic_auth() -> None:
    assert build_default_headers("peer-token", "user:pass") == {
        "A2A-Version": "1.0",
        "Authorization": "Bearer peer-token",
    }


def test_build_default_headers_encodes_basic_auth() -> None:
    assert build_default_headers(None, "user:pass") == {
        "A2A-Version": "1.0",
        "Authorization": "Basic dXNlcjpwYXNz",
    }


def test_build_default_headers_accepts_pre_encoded_basic_auth() -> None:
    assert build_default_headers(None, "dXNlcjpwYXNz") == {
        "A2A-Version": "1.0",
        "Authorization": "Basic dXNlcjpwYXNz",
    }


def test_build_default_headers_rejects_invalid_basic_auth() -> None:
    with pytest.raises(ValueError, match="A2A_CLIENT_BASIC_AUTH"):
        build_default_headers(None, "not-basic-auth")
