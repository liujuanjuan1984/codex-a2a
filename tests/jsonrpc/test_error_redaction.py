from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from a2a.server.jsonrpc_models import InvalidParamsError, JSONRPCError

from codex_a2a.contracts.extensions import (
    DISCOVERY_METHODS,
    EXEC_CONTROL_METHODS,
    INTERRUPT_CALLBACK_METHODS,
    INTERRUPT_RECOVERY_METHODS,
    REVIEW_CONTROL_METHODS,
    SESSION_QUERY_METHODS,
    THREAD_LIFECYCLE_METHODS,
    TURN_CONTROL_METHODS,
    build_capability_snapshot,
)
from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication
from codex_a2a.jsonrpc.errors import adapt_jsonrpc_error, build_http_error_body
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.redact import REDACTED_PATH_PLACEHOLDER
from codex_a2a.upstream.client import CodexClient
from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.settings import make_settings


def test_adapt_jsonrpc_error_redacts_message_and_metadata() -> None:
    error = JSONRPCError(
        code=-32001,
        message="Session file '/home/ubuntu/sessions/s1.json' missing",
        data={
            "type": "SESSION_NOT_FOUND",
            "path": "/home/ubuntu/sessions/s1.json",
            "nested": {"location": r"C:\Users\alice\x"},
        },
    )

    adapted = adapt_jsonrpc_error(error)

    assert adapted.code == -32001
    assert REDACTED_PATH_PLACEHOLDER in adapted.message
    assert "/home/ubuntu/sessions/s1.json" not in adapted.message
    dumped = json.dumps(adapted.data)
    assert REDACTED_PATH_PLACEHOLDER in dumped
    assert "/home/ubuntu/sessions/s1.json" not in dumped
    assert r"C:\Users\alice\x" not in dumped


def test_adapt_jsonrpc_error_redacts_data_for_standard_codes() -> None:
    error = InvalidParamsError(
        message="Invalid params",
        data={"field": "directory", "value": "/home/ubuntu/project"},
    )

    adapted = adapt_jsonrpc_error(error)

    assert adapted.code == -32602
    dumped = json.dumps(adapted.data)
    assert REDACTED_PATH_PLACEHOLDER in dumped
    assert "/home/ubuntu/project" not in dumped


def test_build_http_error_body_redacts_message_and_metadata() -> None:
    body = build_http_error_body(
        status_code=500,
        status="INTERNAL",
        message="Unhandled path /opt/codex/bin/tool",
        metadata={"directory": "/opt/codex/bin"},
    )

    payload = body["error"]
    assert payload["message"] == f"Unhandled path {REDACTED_PATH_PLACEHOLDER}"
    dumped = json.dumps(payload["details"])
    assert REDACTED_PATH_PLACEHOLDER in dumped
    assert "/opt/codex/bin" not in dumped


def _build_app() -> CodexSessionQueryJSONRPCApplication:
    settings = make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, codex_timeout=1.0)
    methods = {
        **SESSION_QUERY_METHODS,
        **DISCOVERY_METHODS,
        "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
        "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
        "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
        "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
        "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
        "thread_watch_release": THREAD_LIFECYCLE_METHODS["watch_release"],
        "interrupts_list": INTERRUPT_RECOVERY_METHODS["list"],
        "turn_steer": TURN_CONTROL_METHODS["steer"],
        "review_start": REVIEW_CONTROL_METHODS["start"],
        "review_watch": REVIEW_CONTROL_METHODS["watch"],
        **EXEC_CONTROL_METHODS,
        **INTERRUPT_CALLBACK_METHODS,
    }
    return CodexSessionQueryJSONRPCApplication(
        request_handler=MagicMock(),
        codex_client=cast(CodexClient, DummyCodexClient(settings)),
        exec_runtime=MagicMock(),
        discovery_runtime=MagicMock(),
        review_runtime=MagicMock(),
        thread_lifecycle_runtime=MagicMock(),
        methods=methods,
        supported_methods=list(
            build_capability_snapshot(
                runtime_profile=build_runtime_profile(settings)
            ).supported_jsonrpc_methods
        ),
        guard_hooks=cast(
            SessionGuardHooks,
            SessionGuardHooks(session_owner_matcher=AsyncMock(return_value=True)),
        ),
    )


def test_generate_error_response_redacts_raw_exception_text() -> None:
    app = _build_app()

    response = app._generate_error_response("1", ValueError("broken at /home/ubuntu/x"))

    body = response.body.decode("utf-8")
    assert REDACTED_PATH_PLACEHOLDER in body
    assert "/home/ubuntu/x" not in body
