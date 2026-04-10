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
    DISCOVERY_METHODS,
    EXEC_CONTROL_METHODS,
    INTERRUPT_CALLBACK_METHODS,
    INTERRUPT_RECOVERY_METHODS,
    REVIEW_CONTROL_METHODS,
    SESSION_CONTROL_METHODS,
    SESSION_QUERY_METHODS,
    THREAD_LIFECYCLE_METHODS,
    TURN_CONTROL_METHODS,
    build_capability_snapshot,
)
from codex_a2a.execution.discovery_runtime import CodexDiscoveryRuntime
from codex_a2a.execution.exec_runtime import CodexExecRuntime
from codex_a2a.execution.executor import CodexAgentExecutor, SessionGuardBindings
from codex_a2a.execution.review_runtime import CodexReviewRuntime
from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.logging_context import install_log_record_factory
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import (
    build_agent_card,
    build_authenticated_extended_agent_card,
)
from codex_a2a.server.call_context import IdentityAwareCallContextBuilder
from codex_a2a.server.database import build_database_engine
from codex_a2a.server.openapi import patch_openapi_contract
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.server.task_store import build_task_store_runtime
from codex_a2a.upstream.client import CodexClient

from .http_middlewares import (
    GZIP_COMPRESSIBLE_PATHS,
    PathScopedGZipMiddleware,
    install_http_middlewares,
)


def _build_session_guard_hooks(
    bindings: SessionGuardBindings,
) -> SessionGuardHooks:
    return SessionGuardHooks(
        directory_resolver=bindings.directory_resolver,
        session_claim=bindings.session_claim,
        session_claim_finalize=bindings.session_claim_finalize,
        session_claim_release=bindings.session_claim_release,
        session_owner_matcher=bindings.session_owner_matcher,
    )


def create_app(settings: Settings) -> FastAPI:
    install_log_record_factory()
    shared_database_engine = (
        build_database_engine(settings) if settings.a2a_database_url is not None else None
    )
    runtime_state_runtime = build_runtime_state_runtime(settings, engine=shared_database_engine)
    client = CodexClient(
        settings,
        interrupt_request_store=runtime_state_runtime.state_store,
    )
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
    task_store_runtime = build_task_store_runtime(settings, engine=shared_database_engine)
    task_store = task_store_runtime.task_store
    handler = CodexRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )
    exec_runtime = CodexExecRuntime(
        client=client,
        request_handler=handler,
    )
    discovery_runtime = CodexDiscoveryRuntime(
        client=client,
        request_handler=handler,
    )
    review_runtime = CodexReviewRuntime(
        client=client,
        request_handler=handler,
    )
    thread_lifecycle_runtime = CodexThreadLifecycleRuntime(
        client=client,
        request_handler=handler,
        state_store=runtime_state_runtime.state_store,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await task_store_runtime.startup()
        await runtime_state_runtime.startup()
        try:
            await client.restore_persisted_interrupt_requests()
            await client.startup_preflight()
            await thread_lifecycle_runtime.reconcile_persisted_watches()
            yield
        finally:
            await a2a_client_manager.close_all()
            await client.close()
            await runtime_state_runtime.shutdown()
            await task_store_runtime.shutdown()
            if shared_database_engine is not None:
                await shared_database_engine.dispose()

    runtime_profile = build_runtime_profile(settings)
    capability_snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    agent_card = build_agent_card(settings, runtime_profile=runtime_profile)
    extended_agent_card = build_authenticated_extended_agent_card(
        settings,
        runtime_profile=runtime_profile,
    )
    context_builder = IdentityAwareCallContextBuilder()
    jsonrpc_methods = {
        **SESSION_QUERY_METHODS,
        **SESSION_CONTROL_METHODS,
        **DISCOVERY_METHODS,
        "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
        "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
        "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
        "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
        "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
        "thread_watch_release": THREAD_LIFECYCLE_METHODS["watch_release"],
        "interrupts_list": INTERRUPT_RECOVERY_METHODS["list"],
        **INTERRUPT_CALLBACK_METHODS,
    }
    if "shell" not in capability_snapshot.session_query_method_keys:
        jsonrpc_methods.pop("shell", None)
    if capability_snapshot.turn_control_methods:
        jsonrpc_methods["turn_steer"] = TURN_CONTROL_METHODS["steer"]
    if capability_snapshot.review_control_methods:
        jsonrpc_methods["review_start"] = REVIEW_CONTROL_METHODS["start"]
        jsonrpc_methods["review_watch"] = REVIEW_CONTROL_METHODS["watch"]
    if capability_snapshot.exec_control_methods:
        jsonrpc_methods.update(EXEC_CONTROL_METHODS)
    session_guard_hooks = _build_session_guard_hooks(executor.session_guard_bindings)

    # Compose the shared FastAPI app from the SDK JSON-RPC and REST application wrappers.
    jsonrpc_app = CodexSessionQueryJSONRPCApplication(
        agent_card=agent_card,
        http_handler=handler,
        extended_agent_card=extended_agent_card,
        context_builder=context_builder,
        codex_client=client,
        exec_runtime=exec_runtime,
        discovery_runtime=discovery_runtime,
        review_runtime=review_runtime,
        thread_lifecycle_runtime=thread_lifecycle_runtime,
        methods=jsonrpc_methods,
        protocol_version=settings.a2a_protocol_version,
        supported_methods=list(capability_snapshot.supported_jsonrpc_methods),
        guard_hooks=session_guard_hooks,
    )
    app = A2AFastAPI(
        title=settings.a2a_title,
        version=settings.a2a_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        PathScopedGZipMiddleware,
        paths=GZIP_COMPRESSIBLE_PATHS,
    )
    jsonrpc_app.add_routes_to_app(app)
    app.state.codex_client = client
    app.state.codex_executor = executor
    app.state.codex_exec_runtime = exec_runtime
    app.state.codex_discovery_runtime = discovery_runtime
    app.state.codex_review_runtime = review_runtime
    app.state.codex_thread_lifecycle_runtime = thread_lifecycle_runtime
    app.state.a2a_client_manager = a2a_client_manager
    app.state.task_store = task_store

    rest_adapter = RESTAdapter(
        agent_card=agent_card,
        http_handler=handler,
        extended_agent_card=extended_agent_card,
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
        agent_card=agent_card,
        extended_agent_card=extended_agent_card,
    )

    patch_openapi_contract(
        app,
        settings=settings,
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
    return "WARNING"


def _configure_logging(level: str) -> None:
    install_log_record_factory()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
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
