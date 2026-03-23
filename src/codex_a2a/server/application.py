from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPI
from a2a.server.apps.rest.rest_adapter import RESTAdapter
from fastapi import FastAPI

from codex_a2a.client import A2AClientManager
from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import (
    INTERRUPT_CALLBACK_METHODS,
    SESSION_CONTROL_METHODS,
    SESSION_QUERY_METHODS,
    build_capability_snapshot,
)
from codex_a2a.execution.directory_policy import resolve_and_validate_directory
from codex_a2a.execution.executor import CodexAgentExecutor
from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.logging_context import install_log_record_factory
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import build_agent_card
from codex_a2a.server.call_context import IdentityAwareCallContextBuilder
from codex_a2a.server.openapi import patch_openapi_contract
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.server.task_store import build_task_store_runtime
from codex_a2a.upstream.client import CodexClient

from .http_middlewares import install_http_middlewares


def create_app(settings: Settings) -> FastAPI:
    install_log_record_factory()
    runtime_state_runtime = build_runtime_state_runtime(settings)
    if runtime_state_runtime.state_store is None:
        client = CodexClient(settings)
    else:
        try:
            client = CodexClient(
                settings,
                interrupt_request_store=runtime_state_runtime.state_store,
            )
        except TypeError:
            client = CodexClient(settings)
    a2a_client_manager = A2AClientManager(settings)
    executor = CodexAgentExecutor(
        client,
        streaming_enabled=True,
        cancel_abort_timeout_seconds=settings.a2a_cancel_abort_timeout_seconds,
        session_cache_ttl_seconds=settings.a2a_session_cache_ttl_seconds,
        session_cache_maxsize=settings.a2a_session_cache_maxsize,
        stream_idle_diagnostic_seconds=settings.a2a_stream_idle_diagnostic_seconds,
        a2a_client_manager=a2a_client_manager,
        session_state_store=runtime_state_runtime.state_store,
    )
    task_store_runtime = build_task_store_runtime(settings)
    task_store = task_store_runtime.task_store
    handler = CodexRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await task_store_runtime.startup()
        await runtime_state_runtime.startup()
        try:
            restore_interrupts = getattr(client, "restore_persisted_interrupt_requests", None)
            if callable(restore_interrupts):
                await restore_interrupts()
            startup_preflight = getattr(client, "startup_preflight", None)
            if callable(startup_preflight):
                await startup_preflight()
            yield
        finally:
            await a2a_client_manager.close_all()
            await client.close()
            await runtime_state_runtime.shutdown()
            await task_store_runtime.shutdown()

    runtime_profile = build_runtime_profile(settings)
    capability_snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    agent_card = build_agent_card(settings, runtime_profile=runtime_profile)
    context_builder = IdentityAwareCallContextBuilder()
    jsonrpc_methods = {
        **SESSION_QUERY_METHODS,
        **SESSION_CONTROL_METHODS,
        **INTERRUPT_CALLBACK_METHODS,
    }
    if "shell" not in capability_snapshot.session_query_method_keys:
        jsonrpc_methods.pop("shell", None)

    # Compose the shared FastAPI app from the SDK JSON-RPC and REST application wrappers.
    jsonrpc_app = CodexSessionQueryJSONRPCApplication(
        agent_card=agent_card,
        http_handler=handler,
        context_builder=context_builder,
        codex_client=client,
        methods=jsonrpc_methods,
        protocol_version=settings.a2a_protocol_version,
        supported_methods=list(capability_snapshot.supported_jsonrpc_methods),
        guard_hooks=SessionGuardHooks(
            directory_resolver=lambda requested: resolve_and_validate_directory(client, requested),
            session_claim=executor._session_runtime.claim_session,
            session_claim_finalize=executor._session_runtime.finalize_session_claim,
            session_claim_release=executor._session_runtime.release_session_claim,
            session_owner_matcher=executor._session_runtime.session_owner_matches,
        ),
    )
    app = A2AFastAPI(
        title=settings.a2a_title,
        version=settings.a2a_version,
        lifespan=lifespan,
    )
    jsonrpc_app.add_routes_to_app(app)
    app.state.codex_client = client
    app.state.codex_executor = executor
    app.state.a2a_client_manager = a2a_client_manager
    app.state.task_store = task_store

    rest_adapter = RESTAdapter(
        agent_card=agent_card,
        http_handler=handler,
        context_builder=context_builder,
    )
    for route, callback in rest_adapter.routes().items():
        app.add_api_route(route[0], callback, methods=[route[1]])

    if settings.a2a_enable_health_endpoint:

        @app.get("/health")
        async def health_check():
            return runtime_profile.health_payload(
                service="codex-a2a",
                version=settings.a2a_version,
            )

    install_http_middlewares(
        app,
        settings=settings,
        task_store=task_store,
    )

    patch_openapi_contract(
        app,
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )

    app_status_cls: Any | None = None
    try:
        from sse_starlette.sse import AppStatus as app_status_cls
    except ImportError:  # pragma: no cover - optional dependency
        pass
    if app_status_cls is not None:
        app_status_cls.should_exit = False
        app_status_cls.should_exit_event = None

    return app


def _normalize_log_level(value: str) -> str:
    normalized = (value or "").strip().upper()
    if normalized in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        return normalized
    return "INFO"


def _configure_logging(level: str) -> None:
    install_log_record_factory()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s [correlation_id=%(correlation_id)s]: %(message)s"
        ),
    )
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings)
    log_level = _normalize_log_level(settings.a2a_log_level)
    _configure_logging(log_level)
    uvicorn.run(app, host=settings.a2a_host, port=settings.a2a_port, log_level=log_level.lower())


if __name__ == "__main__":
    main()
