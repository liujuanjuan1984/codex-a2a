from unittest.mock import AsyncMock, MagicMock

import pytest

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
from codex_a2a.jsonrpc.application import (
    CodexSessionQueryJSONRPCApplication,
    create_codex_jsonrpc_routes,
)
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.profile.runtime import build_runtime_profile
from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.settings import make_settings


def _build_extension_app(
    *,
    guard_hooks: SessionGuardHooks | None = None,
) -> CodexSessionQueryJSONRPCApplication:
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
        codex_client=DummyCodexClient(settings),
        exec_runtime=MagicMock(),
        discovery_runtime=MagicMock(),
        review_runtime=MagicMock(),
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
    async def owner_matcher(*, identity: str, session_id: str) -> bool:
        del identity, session_id
        return True

    app = _build_extension_app(
        guard_hooks=SessionGuardHooks(
            session_owner_matcher=owner_matcher,
        )
    )

    assert app._guard_hooks.session_owner_matcher is owner_matcher


def test_session_extension_guard_hook_bundle_fails_when_incomplete() -> None:
    with pytest.raises(ValueError, match="missing required interrupt ownership hook"):
        _build_extension_app(guard_hooks=SessionGuardHooks())


def test_create_codex_jsonrpc_routes_returns_single_post_route() -> None:
    settings = make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, codex_timeout=1.0)
    guard_hooks = SessionGuardHooks(
        session_owner_matcher=AsyncMock(return_value=True),
    )
    captured: dict[str, object] = {}

    class DummyDispatcher:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            captured.update(kwargs)
            self.handle_requests = AsyncMock()

    routes = create_codex_jsonrpc_routes(
        request_handler=MagicMock(),
        context_builder=MagicMock(),
        codex_client=DummyCodexClient(settings),
        exec_runtime=MagicMock(),
        discovery_runtime=MagicMock(),
        review_runtime=MagicMock(),
        thread_lifecycle_runtime=MagicMock(),
        methods={
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
        },
        protocol_version=settings.a2a_protocol_version,
        supported_methods=list(
            build_capability_snapshot(
                runtime_profile=build_runtime_profile(settings)
            ).supported_jsonrpc_methods
        ),
        guard_hooks=guard_hooks,
        rpc_url="/rpc",
        dispatcher_factory=DummyDispatcher,
    )

    assert len(routes) == 1
    assert routes[0].path == "/rpc"
    assert routes[0].methods == {"POST"}
    assert captured["guard_hooks"] is guard_hooks
