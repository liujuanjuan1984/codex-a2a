from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.rest_dispatcher import RestDispatcher
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.types import SubscribeToTaskRequest, a2a_pb2
from a2a.utils import proto_utils
from a2a.utils.error_handlers import build_rest_error_payload
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict, Parse  # type: ignore[import-untyped]
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
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
from codex_a2a.jsonrpc.errors import build_http_error_body
from codex_a2a.jsonrpc.extension_policy import ExtensionActivationAuthorizer
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.logging_context import install_log_record_factory
from codex_a2a.metrics import get_metrics_registry
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import (
    build_agent_card,
    build_authenticated_extended_agent_card,
)
from codex_a2a.server.call_context import IdentityAwareCallContextBuilder
from codex_a2a.server.database import build_database_engine
from codex_a2a.server.openapi import patch_openapi_contract
from codex_a2a.server.push_config_store import build_push_config_store_runtime
from codex_a2a.server.request_handler import CodexRequestHandler
from codex_a2a.server.runtime_limits import (
    OperationCapacity,
    OperationCapacityMiddleware,
    RequestBodyLimitMiddleware,
    StreamBudgetExceeded,
    apply_stream_budget,
)
from codex_a2a.server.runtime_state import build_runtime_state_runtime
from codex_a2a.server.task_store import build_task_store_runtime, describe_persistence_backend
from codex_a2a.upstream.client import CodexClient

from .http_middlewares import (
    GZIP_COMPRESSIBLE_PATHS,
    PathScopedGZipMiddleware,
    install_http_middlewares,
)

logger = logging.getLogger(__name__)


def _is_sdk_tenant_mount(route: BaseRoute) -> bool:
    return isinstance(route, Mount) and route.path == "/{tenant}"


_STREAMING_REST_PATHS = frozenset({"/message:stream", "/tasks/{id}:subscribe"})
_STREAM_BUDGET_REJECT_REASON = "STREAM_BUDGET_EXCEEDED"


class BudgetedRestDispatcher(RestDispatcher):
    """REST dispatcher that applies streaming output budgets to SSE streams."""

    def __init__(
        self,
        request_handler: Any,
        context_builder: Any,
        *,
        stream_budget_max_bytes: int,
        stream_budget_max_duration_seconds: float,
        stream_budget_idle_timeout_seconds: float,
    ) -> None:
        super().__init__(
            request_handler=request_handler,
            context_builder=context_builder,
        )
        self._stream_budget_max_bytes = stream_budget_max_bytes
        self._stream_budget_max_duration_seconds = stream_budget_max_duration_seconds
        self._stream_budget_idle_timeout_seconds = stream_budget_idle_timeout_seconds

    async def _handle_streaming(
        self,
        request: Request,
        handler_func: Any,
    ) -> Any:
        async def budgeted_handler(context: Any) -> Any:
            async for item in apply_stream_budget(
                aiter(handler_func(context)),
                max_bytes=self._stream_budget_max_bytes,
                max_duration_seconds=self._stream_budget_max_duration_seconds,
                idle_timeout_seconds=self._stream_budget_idle_timeout_seconds,
            ):
                yield item

        return await super()._handle_streaming(request, budgeted_handler)


def _stream_budget_error_response(error: StreamBudgetExceeded) -> JSONResponse:
    return JSONResponse(
        build_http_error_body(
            status_code=429,
            status="RESOURCE_EXHAUSTED",
            message=str(error),
            reason=_STREAM_BUDGET_REJECT_REASON,
        ),
        status_code=429,
    )


def _rest_error_response(error: Exception) -> JSONResponse:
    """Map a pre-SSE error to the same REST error payload the SDK emits."""
    payload = build_rest_error_payload(error)
    http_code = payload.get("error", {}).get("code", 500)
    return JSONResponse(content=payload, status_code=http_code)


def _create_single_tenant_rest_routes(
    *,
    request_handler: Any,
    context_builder: Any = None,
    path_prefix: str = "",
    enable_v0_3_compat: bool = False,
    stream_budget_max_bytes: int = 0,
    stream_budget_max_duration_seconds: float = 0.0,
    stream_budget_idle_timeout_seconds: float = 0.0,
) -> list[BaseRoute]:
    # The SDK exposes a tenant-prefixed REST alias by default. This service's
    # supported HTTP+JSON contract is the spec-rooted single-tenant surface
    # (A2A 1.0 resolves REST paths from the advertised interface URL, with no
    # version prefix in the URL), so the application assembly narrows the route
    # set explicitly and replaces the streaming routes with budgeted ones.
    sdk_routes = create_rest_routes(
        request_handler=request_handler,
        context_builder=context_builder,
        enable_v0_3_compat=enable_v0_3_compat,
        path_prefix=path_prefix,
    )
    base_routes = [route for route in sdk_routes if not _is_sdk_tenant_mount(route)]

    dispatcher = BudgetedRestDispatcher(
        request_handler=request_handler,
        context_builder=context_builder,
        stream_budget_max_bytes=stream_budget_max_bytes,
        stream_budget_max_duration_seconds=stream_budget_max_duration_seconds,
        stream_budget_idle_timeout_seconds=stream_budget_idle_timeout_seconds,
    )

    async def _handle_streaming_route(request: Request, handler_func: Any) -> Response:
        try:
            return await dispatcher._handle_streaming(request, handler_func)
        except StreamBudgetExceeded as error:
            return _stream_budget_error_response(error)
        except Exception as error:  # noqa: BLE001 - mirrors SDK rest_stream_error_handler
            return _rest_error_response(error)

    async def message_stream_route(request: Request) -> Response:
        async def _handler(context: Any) -> Any:
            body = await request.body()
            params = a2a_pb2.SendMessageRequest()
            Parse(body, params)
            async for event in request_handler.on_message_send_stream(params, context):
                yield MessageToDict(proto_utils.to_stream_response(event))

        return await _handle_streaming_route(request, _handler)

    async def subscribe_route(request: Request) -> Response:
        task_id = request.path_params["id"]

        async def _handler(context: Any) -> Any:
            async for event in request_handler.on_subscribe_to_task(
                SubscribeToTaskRequest(id=task_id),
                context,
            ):
                yield MessageToDict(proto_utils.to_stream_response(event))

        return await _handle_streaming_route(request, _handler)

    prefixed_streaming_paths = {f"{path_prefix}{path}" for path in _STREAMING_REST_PATHS}
    retained = [
        route
        for route in base_routes
        if not (hasattr(route, "path") and route.path in prefixed_streaming_paths)
    ]
    streaming_routes = [
        Route(
            path=f"{path_prefix}/message:stream",
            endpoint=message_stream_route,
            methods=["POST"],
        ),
        Route(
            path=f"{path_prefix}/tasks/{{id}}:subscribe",
            endpoint=subscribe_route,
            methods=["GET"],
        ),
        Route(
            path=f"{path_prefix}/tasks/{{id}}:subscribe",
            endpoint=subscribe_route,
            methods=["POST"],
        ),
    ]
    return retained + streaming_routes


def create_app(
    settings: Settings,
    *,
    extension_activation_authorizer: ExtensionActivationAuthorizer | None = None,
) -> FastAPI:
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
        **{
            key: method
            for key, method in extension_contracts.DISCOVERY_METHODS.items()
            if method in capability_snapshot.discovery_methods
        },
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
    operation_capacity = OperationCapacity(settings.a2a_max_concurrent_operations)
    app.add_middleware(
        OperationCapacityMiddleware,
        capacity=operation_capacity,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.a2a_request_body_max_bytes,
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
            extension_activation_authorizer=extension_activation_authorizer,
            rpc_url=extension_contracts.CORE_JSONRPC_PATH,
            dispatcher_factory=CodexSessionQueryJSONRPCApplication,
            stream_budget_max_bytes=settings.a2a_stream_max_bytes,
            stream_budget_max_duration_seconds=settings.a2a_stream_max_duration_seconds,
            stream_budget_idle_timeout_seconds=settings.a2a_stream_idle_timeout_seconds,
        )
    )
    app.router.routes.extend(
        _create_single_tenant_rest_routes(
            request_handler=handler,
            context_builder=context_builder,
            # A2A 1.0 roots the HTTP+JSON surface at the service root; the SDK
            # default prefix is empty, matching the URL the Agent Card advertises.
            path_prefix="",
            stream_budget_max_bytes=settings.a2a_stream_max_bytes,
            stream_budget_max_duration_seconds=settings.a2a_stream_max_duration_seconds,
            stream_budget_idle_timeout_seconds=settings.a2a_stream_idle_timeout_seconds,
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
    app.state.operation_capacity = operation_capacity
    app.state.metrics_registry = get_metrics_registry()

    if settings.a2a_enable_health_endpoint:

        @app.get("/health")
        async def health_check():
            return runtime_profile.health_payload(
                service="codex-a2a",
                version=settings.a2a_version,
            )

        @app.get("/ready")
        async def readiness_check():
            ready = client.ready
            status = "ready" if ready else "not_ready"
            return JSONResponse(
                {"status": status, "checks": {"codex_app_server": status}},
                status_code=200 if ready else 503,
            )

    if settings.a2a_enable_metrics_endpoint:

        @app.get("/metrics")
        async def metrics():
            return PlainTextResponse(
                get_metrics_registry().render_prometheus(),
                media_type="text/plain; version=0.0.4",
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
