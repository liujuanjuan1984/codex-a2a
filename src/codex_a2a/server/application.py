from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.rest_routes import create_rest_routes
from fastapi import FastAPI
from starlette.routing import BaseRoute, Mount, Route

from codex_a2a.client.manager import A2AClientManager
from codex_a2a.config import Settings
from codex_a2a.contracts import extensions as extension_contracts
from codex_a2a.execution.discovery_runtime import CodexDiscoveryRuntime
from codex_a2a.execution.exec_runtime import CodexExecRuntime
from codex_a2a.execution.executor import CodexAgentExecutor
from codex_a2a.execution.review_runtime import CodexReviewRuntime
from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from codex_a2a.jsonrpc.application import (
    CodexSessionQueryJSONRPCApplication,
    create_extension_jsonrpc_routes,
)
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.logging_context import install_log_record_factory
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.protocol_versions import (
    LEGACY_COMPAT_PROTOCOL_VERSION,
    get_current_protocol_version,
)
from codex_a2a.server.agent_card import (
    build_agent_card,
    build_authenticated_extended_agent_card,
)
from codex_a2a.server.call_context import IdentityAwareCallContextBuilder
from codex_a2a.server.database import build_database_engine
from codex_a2a.server.openapi import patch_openapi_contract
from codex_a2a.server.push_config_store import build_push_config_store_runtime
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.server.task_store import build_task_store_runtime, describe_persistence_backend
from codex_a2a.upstream.client import CodexClient

from .http_middlewares import (
    GZIP_COMPRESSIBLE_PATHS,
    PathScopedGZipMiddleware,
    install_http_middlewares,
)

logger = logging.getLogger(__name__)


def _flatten_rest_routes(
    routes: list[BaseRoute],
    *,
    prefix: str = "",
) -> list[tuple[str, str, Any, str | None]]:
    flattened: list[tuple[str, str, Any, str | None]] = []
    for route in routes:
        if isinstance(route, Route):
            methods = sorted((route.methods or set()) - {"HEAD"})
            if len(methods) != 1:
                continue
            flattened.append((f"{prefix}{route.path}", methods[0], route.endpoint, route.name))
            continue
        if isinstance(route, Mount):
            flattened.extend(
                _flatten_rest_routes(
                    list(route.routes),
                    prefix=f"{prefix}{route.path}",
                )
            )
    return flattened


def _extract_compat_rest_routes(
    *,
    request_handler,
    context_builder,
    path_prefix: str,
) -> list[tuple[str, str, Any, str | None]]:
    compat_prefix = f"{path_prefix}{extension_contracts.REST_API_PATH_PREFIX}"
    compat_card_path = f"{compat_prefix}/card"
    routes = create_rest_routes(
        request_handler=request_handler,
        context_builder=context_builder,
        enable_v0_3_compat=True,
        path_prefix=path_prefix,
    )
    return [
        route
        for route in _flatten_rest_routes(routes)
        if route[0].startswith(f"{compat_prefix}/") or route[0] == compat_card_path
    ]


def _merge_dual_stack_rest_routes(
    *,
    base_routes: list[tuple[str, str, Any, str | None]],
    compat_routes: list[tuple[str, str, Any, str | None]],
) -> list[Route]:
    compat_route_map = {
        (path, method): (endpoint, name) for path, method, endpoint, name in compat_routes
    }
    merged_routes: list[Route] = []

    for path, method, base_endpoint, name in base_routes:
        compat_endpoint = compat_route_map.pop((path, method), None)
        if compat_endpoint is None:
            merged_routes.append(
                Route(
                    path=path,
                    endpoint=base_endpoint,
                    methods=[method],
                    name=name,
                )
            )
            continue

        async def _dispatch(
            request,
            *,
            base_endpoint=base_endpoint,
            compat_endpoint=compat_endpoint[0],
        ):
            if get_current_protocol_version() == LEGACY_COMPAT_PROTOCOL_VERSION:
                return await compat_endpoint(request)
            return await base_endpoint(request)

        merged_routes.append(
            Route(
                path=path,
                endpoint=_dispatch,
                methods=[method],
                name=name,
            )
        )

    for (path, method), (compat_endpoint, name) in compat_route_map.items():
        merged_routes.append(
            Route(
                path=path,
                endpoint=compat_endpoint,
                methods=[method],
                name=name,
            )
        )

    return merged_routes


def _create_dual_stack_rest_routes(
    *,
    request_handler,
    context_builder,
) -> list[Any]:
    base_routes = _flatten_rest_routes(
        create_rest_routes(
            request_handler=request_handler,
            context_builder=context_builder,
            path_prefix=extension_contracts.REST_API_PATH_PREFIX,
        )
    )
    compat_routes = _extract_compat_rest_routes(
        request_handler=request_handler,
        context_builder=context_builder,
        path_prefix="",
    )
    compat_routes.extend(
        _extract_compat_rest_routes(
            request_handler=request_handler,
            context_builder=context_builder,
            path_prefix="/{tenant}",
        )
    )
    return _merge_dual_stack_rest_routes(
        base_routes=base_routes,
        compat_routes=compat_routes,
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
    push_config_store_runtime = build_push_config_store_runtime(
        settings,
        engine=shared_database_engine,
    )
    task_store = task_store_runtime.task_store
    persistence_summary = describe_persistence_backend(settings)
    runtime_profile = build_runtime_profile(settings)
    capability_snapshot = extension_contracts.build_capability_snapshot(
        runtime_profile=runtime_profile
    )
    agent_card = build_agent_card(settings, runtime_profile=runtime_profile)
    extended_agent_card = build_authenticated_extended_agent_card(
        settings,
        runtime_profile=runtime_profile,
    )
    handler = CodexRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        push_config_store=push_config_store_runtime.push_config_store,
        agent_card=agent_card,
        extended_agent_card=extended_agent_card,
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
        logger.info(
            "A2A persistence configured backend=%s task_store=%s push_config_store=%s "
            "runtime_state=%s database_url=%s sqlite_tuning=%s",
            persistence_summary["backend"],
            persistence_summary["task_store"],
            persistence_summary["push_config_store"],
            persistence_summary["runtime_state"],
            persistence_summary["database_url"],
            persistence_summary["sqlite_tuning"],
        )
        await task_store_runtime.startup()
        await push_config_store_runtime.startup()
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
            await push_config_store_runtime.shutdown()
            await task_store_runtime.shutdown()
            if shared_database_engine is not None:
                await shared_database_engine.dispose()

    context_builder = IdentityAwareCallContextBuilder()
    jsonrpc_methods = {
        **extension_contracts.SESSION_QUERY_METHODS,
        **extension_contracts.DISCOVERY_METHODS,
        "thread_fork": extension_contracts.THREAD_LIFECYCLE_METHODS["fork"],
        "thread_archive": extension_contracts.THREAD_LIFECYCLE_METHODS["archive"],
        "thread_unarchive": extension_contracts.THREAD_LIFECYCLE_METHODS["unarchive"],
        "thread_metadata_update": extension_contracts.THREAD_LIFECYCLE_METHODS["metadata_update"],
        "thread_watch": extension_contracts.THREAD_LIFECYCLE_METHODS["watch"],
        "thread_watch_release": extension_contracts.THREAD_LIFECYCLE_METHODS["watch_release"],
        "interrupts_list": extension_contracts.INTERRUPT_RECOVERY_METHODS["list"],
        **extension_contracts.INTERRUPT_CALLBACK_METHODS,
    }
    if capability_snapshot.turn_control_methods:
        jsonrpc_methods["turn_steer"] = extension_contracts.TURN_CONTROL_METHODS["steer"]
    if capability_snapshot.review_control_methods:
        jsonrpc_methods["review_start"] = extension_contracts.REVIEW_CONTROL_METHODS["start"]
        jsonrpc_methods["review_watch"] = extension_contracts.REVIEW_CONTROL_METHODS["watch"]
    if capability_snapshot.exec_control_methods:
        jsonrpc_methods.update(extension_contracts.EXEC_CONTROL_METHODS)
    bindings = executor.session_guard_bindings
    session_guard_hooks = SessionGuardHooks(
        directory_resolver=bindings.directory_resolver,
        session_claim=bindings.session_claim,
        session_claim_finalize=bindings.session_claim_finalize,
        session_claim_release=bindings.session_claim_release,
        session_owner_matcher=bindings.session_owner_matcher,
    )

    supported_extension_jsonrpc_methods = list(capability_snapshot.extension_jsonrpc_methods)
    app = FastAPI(
        title=settings.a2a_title,
        version=settings.a2a_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        PathScopedGZipMiddleware,
        paths=GZIP_COMPRESSIBLE_PATHS,
    )
    app.router.routes.extend(create_agent_card_routes(agent_card))
    app.router.routes.extend(
        create_extension_jsonrpc_routes(
            request_handler=handler,
            context_builder=context_builder,
            codex_client=client,
            exec_runtime=exec_runtime,
            discovery_runtime=discovery_runtime,
            review_runtime=review_runtime,
            thread_lifecycle_runtime=thread_lifecycle_runtime,
            methods=jsonrpc_methods,
            supported_methods=supported_extension_jsonrpc_methods,
            guard_hooks=session_guard_hooks,
            rpc_url=extension_contracts.CORE_JSONRPC_PATH,
            enable_v0_3_compat=True,
            dispatcher_factory=CodexSessionQueryJSONRPCApplication,
        )
    )
    app.router.routes.extend(
        _create_dual_stack_rest_routes(
            request_handler=handler,
            context_builder=context_builder,
        )
    )
    app.state.codex_client = client
    app.state.codex_executor = executor
    app.state.codex_exec_runtime = exec_runtime
    app.state.codex_discovery_runtime = discovery_runtime
    app.state.codex_review_runtime = review_runtime
    app.state.codex_thread_lifecycle_runtime = thread_lifecycle_runtime
    app.state.a2a_client_manager = a2a_client_manager
    app.state.task_store = task_store
    app.state.push_config_store = push_config_store_runtime.push_config_store

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
