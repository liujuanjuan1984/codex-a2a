from unittest.mock import MagicMock

import pytest

from codex_a2a.contracts.extensions import (
    DISCOVERY_METHODS,
    EXEC_CONTROL_METHODS,
    INTERRUPT_CALLBACK_METHODS,
    SESSION_CONTROL_METHODS,
    SESSION_QUERY_METHODS,
    THREAD_LIFECYCLE_METHODS,
    build_capability_snapshot,
)
from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import build_agent_card
from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.settings import make_settings


def _build_extension_app(
    *,
    guard_hooks: SessionGuardHooks | None = None,
) -> CodexSessionQueryJSONRPCApplication:
    settings = make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, codex_timeout=1.0)
    methods = {
        **SESSION_QUERY_METHODS,
        **SESSION_CONTROL_METHODS,
        **DISCOVERY_METHODS,
        "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
        "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
        "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
        "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
        "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
        **EXEC_CONTROL_METHODS,
        **INTERRUPT_CALLBACK_METHODS,
    }
    return CodexSessionQueryJSONRPCApplication(
        agent_card=build_agent_card(settings),
        http_handler=MagicMock(),
        codex_client=DummyCodexClient(settings),
        exec_runtime=MagicMock(),
        discovery_runtime=MagicMock(),
        thread_lifecycle_runtime=MagicMock(),
        methods=methods,
        protocol_version=settings.a2a_protocol_version,
        supported_methods=list(
            build_capability_snapshot(
                runtime_profile=build_runtime_profile(settings)
            ).supported_jsonrpc_methods
        ),
        guard_hooks=guard_hooks,
    )


def test_session_extension_accepts_guard_hook_bundle() -> None:
    async def claim(*, identity: str, session_id: str) -> bool:
        del identity, session_id
        return False

    async def finalize(*, identity: str, session_id: str) -> None:
        del identity, session_id

    async def release(*, identity: str, session_id: str) -> None:
        del identity, session_id

    async def owner_matcher(*, identity: str, session_id: str) -> bool:
        del identity, session_id
        return True

    app = _build_extension_app(
        guard_hooks=SessionGuardHooks(
            session_claim=claim,
            session_claim_finalize=finalize,
            session_claim_release=release,
            session_owner_matcher=owner_matcher,
        )
    )

    assert app._guard_hooks.session_claim is claim
    assert app._guard_hooks.session_claim_finalize is finalize
    assert app._guard_hooks.session_claim_release is release
    assert app._guard_hooks.session_owner_matcher is owner_matcher


def test_session_extension_guard_hook_bundle_fails_when_incomplete() -> None:
    async def owner_matcher(*, identity: str, session_id: str) -> bool:
        del identity, session_id
        return True

    with pytest.raises(ValueError, match="missing required session control hooks"):
        _build_extension_app(guard_hooks=SessionGuardHooks(session_owner_matcher=owner_matcher))
