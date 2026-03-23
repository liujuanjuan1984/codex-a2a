from __future__ import annotations

from codex_a2a.client.request_context import build_call_context, split_request_metadata


def test_split_request_metadata_separates_authorization_header() -> None:
    request_metadata, extra_headers = split_request_metadata(
        {"authorization": "Bearer explicit-token", "trace_id": "trace-1"}
    )

    assert request_metadata == {"trace_id": "trace-1"}
    assert extra_headers == {"Authorization": "Bearer explicit-token"}


def test_split_request_metadata_ignores_empty_input() -> None:
    request_metadata, extra_headers = split_request_metadata(None)

    assert request_metadata is None
    assert extra_headers is None


def test_build_call_context_returns_header_state() -> None:
    context = build_call_context({"Authorization": "Bearer explicit-token"})

    assert context is not None
    assert context.state["headers"] == {"Authorization": "Bearer explicit-token"}


def test_build_call_context_returns_none_without_headers() -> None:
    assert build_call_context(None) is None
