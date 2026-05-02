from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from codex_a2a.execution.request_metadata import (
    extract_codex_execution_options,
    extract_shared_session_id,
)
from codex_a2a.execution.request_overrides import RequestExecutionOptionsValidationError


def test_extract_shared_session_id_logs_and_falls_back_when_context_metadata_is_unparseable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken_metadata = object()
    context = SimpleNamespace(
        metadata=broken_metadata,
        message=SimpleNamespace(metadata={"shared": {"session": {"id": "sess-1"}}}),
    )

    original = extract_shared_session_id.__globals__["_metadata_mapping"]

    def flaky_metadata_mapping(value):  # noqa: ANN001
        if value is broken_metadata:
            raise ValueError("bad metadata")
        return original(value)

    monkeypatch.setitem(
        extract_shared_session_id.__globals__,
        "_metadata_mapping",
        flaky_metadata_mapping,
    )

    caplog.set_level(logging.DEBUG, logger="codex_a2a.execution.request_metadata")

    assert extract_shared_session_id(context) == "sess-1"
    assert "Ignoring unparseable request metadata while extracting shared.session.id" in caplog.text
    assert "bad metadata" in caplog.text


def test_extract_codex_execution_options_logs_and_uses_message_metadata_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken_metadata = object()
    context = SimpleNamespace(
        metadata=broken_metadata,
        message=SimpleNamespace(
            metadata={
                "codex": {
                    "execution": {
                        "model": "gpt-5.5",
                        "effort": "high",
                        "summary": "concise",
                    }
                }
            }
        ),
    )

    original = extract_codex_execution_options.__globals__["_metadata_mapping"]

    def flaky_metadata_mapping(value):  # noqa: ANN001
        if value is broken_metadata:
            raise TypeError("cannot normalize metadata")
        return original(value)

    monkeypatch.setitem(
        extract_codex_execution_options.__globals__,
        "_metadata_mapping",
        flaky_metadata_mapping,
    )

    caplog.set_level(logging.DEBUG, logger="codex_a2a.execution.request_metadata")

    options = extract_codex_execution_options(context)

    assert options.model == "gpt-5.5"
    assert options.effort == "high"
    assert options.summary == "concise"
    assert options.personality is None
    assert "Ignoring unparseable request metadata while extracting codex.execution options" in (
        caplog.text
    )


def test_extract_codex_execution_options_still_validates_normalized_metadata() -> None:
    context = SimpleNamespace(
        metadata={"codex": {"execution": "invalid"}},
        message=None,
    )

    with pytest.raises(RequestExecutionOptionsValidationError) as exc_info:
        extract_codex_execution_options(context)

    assert exc_info.value.field == "metadata.codex.execution"
    assert str(exc_info.value) == "metadata.codex.execution must be an object"
