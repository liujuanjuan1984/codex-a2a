from __future__ import annotations

from typing import Any

from a2a.server.jsonrpc_models import InvalidParamsError, JSONRPCError
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.utils.errors import A2AError
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from codex_a2a.execution.discovery_runtime import CodexDiscoveryRuntime
from codex_a2a.execution.exec_runtime import CodexExecRuntime
from codex_a2a.execution.review_runtime import CodexReviewRuntime
from codex_a2a.execution.thread_lifecycle_runtime import CodexThreadLifecycleRuntime
from codex_a2a.jsonrpc.discovery_control import handle_discovery_control_request
from codex_a2a.jsonrpc.discovery_query import handle_discovery_query_request
from codex_a2a.jsonrpc.dispatch import ExtensionMethodRegistry
from codex_a2a.jsonrpc.errors import adapt_jsonrpc_error
from codex_a2a.jsonrpc.exec_control import handle_exec_control_request
from codex_a2a.jsonrpc.hooks import SessionGuardHooks
from codex_a2a.jsonrpc.interrupt_recovery import handle_interrupt_recovery_request
from codex_a2a.jsonrpc.interrupts import handle_interrupt_callback_request
from codex_a2a.jsonrpc.request_models import JSONRPCRequestModel
from codex_a2a.jsonrpc.review_control import handle_review_control_request
from codex_a2a.jsonrpc.session_control import handle_session_control_request
from codex_a2a.jsonrpc.session_query import handle_session_query_request
from codex_a2a.jsonrpc.thread_lifecycle_control import handle_thread_lifecycle_control_request
from codex_a2a.jsonrpc.turn_control import handle_turn_control_request
from codex_a2a.protocol_versions import get_current_protocol_version
from codex_a2a.upstream.client import CodexClient


def create_codex_jsonrpc_routes(
    *,
    request_handler,
    context_builder,
    codex_client: CodexClient,
    exec_runtime: CodexExecRuntime,
    discovery_runtime: CodexDiscoveryRuntime,
    review_runtime: CodexReviewRuntime,
    thread_lifecycle_runtime: CodexThreadLifecycleRuntime,
    methods: dict[str, str],
    protocol_version: str,
    supported_methods: list[str],
    guard_hooks: SessionGuardHooks,
    rpc_url: str,
    dispatcher_factory=None,
) -> list[Route]:
    factory = dispatcher_factory or CodexSessionQueryJSONRPCApplication
    dispatcher = factory(
        request_handler=request_handler,
        context_builder=context_builder,
        codex_client=codex_client,
        exec_runtime=exec_runtime,
        discovery_runtime=discovery_runtime,
        review_runtime=review_runtime,
        thread_lifecycle_runtime=thread_lifecycle_runtime,
        methods=methods,
        protocol_version=protocol_version,
        supported_methods=supported_methods,
        guard_hooks=guard_hooks,
    )
    return [
        Route(
            path=rpc_url,
            endpoint=dispatcher.handle_requests,
            methods=["POST"],
        )
    ]


class CodexSessionQueryJSONRPCApplication(JsonRpcDispatcher):
    """Extend the SDK JSON-RPC dispatcher with Codex-specific extension methods."""

    def __init__(
        self,
        *args: Any,
        codex_client: CodexClient,
        exec_runtime: CodexExecRuntime,
        discovery_runtime: CodexDiscoveryRuntime,
        review_runtime: CodexReviewRuntime,
        thread_lifecycle_runtime: CodexThreadLifecycleRuntime,
        methods: dict[str, str],
        protocol_version: str,
        supported_methods: list[str],
        guard_hooks: SessionGuardHooks,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._codex_client = codex_client
        self._exec_runtime = exec_runtime
        self._discovery_runtime = discovery_runtime
        self._review_runtime = review_runtime
        self._thread_lifecycle_runtime = thread_lifecycle_runtime
        self._method_list_sessions = methods["list_sessions"]
        self._method_get_session_messages = methods["get_session_messages"]
        self._method_prompt_async = methods["prompt_async"]
        self._method_command = methods["command"]
        self._method_shell = methods.get("shell")
        self._method_discovery_skills_list = methods["list_skills"]
        self._method_discovery_apps_list = methods["list_apps"]
        self._method_discovery_plugins_list = methods["list_plugins"]
        self._method_thread_fork = methods["thread_fork"]
        self._method_thread_archive = methods["thread_archive"]
        self._method_thread_unarchive = methods["thread_unarchive"]
        self._method_thread_metadata_update = methods["thread_metadata_update"]
        self._method_thread_watch = methods["thread_watch"]
        self._method_thread_watch_release = methods["thread_watch_release"]
        self._method_review_watch = methods.get("review_watch")
        self._method_exec_start = methods.get("exec_start")
        self._method_exec_write = methods.get("exec_write")
        self._method_exec_resize = methods.get("exec_resize")
        self._method_reply_permission = methods["reply_permission"]
        self._method_reply_question = methods["reply_question"]
        self._method_reject_question = methods["reject_question"]
        self._method_reply_permissions = methods["reply_permissions"]
        self._method_reply_elicitation = methods["reply_elicitation"]
        self._interrupt_methods_by_type = {
            "permission": self._method_reply_permission,
            "question": self._method_reply_question,
            "permissions": self._method_reply_permissions,
            "elicitation": self._method_reply_elicitation,
        }
        self._protocol_version = protocol_version
        self._supported_methods = list(supported_methods)
        self._supported_method_set = set(supported_methods)
        self._method_registry = ExtensionMethodRegistry.from_methods(methods)
        self._guard_hooks = guard_hooks
        self._validate_guard_hooks()

    def _validate_guard_hooks(self) -> None:
        missing_for_session_control: list[str] = []
        if self._guard_hooks.session_claim is None:
            missing_for_session_control.append("session_claim")
        if self._guard_hooks.session_claim_finalize is None:
            missing_for_session_control.append("session_claim_finalize")
        if self._guard_hooks.session_claim_release is None:
            missing_for_session_control.append("session_claim_release")
        if missing_for_session_control:
            missing = ", ".join(missing_for_session_control)
            raise ValueError(
                "CodexSessionQueryJSONRPCApplication missing required session control hooks: "
                f"{missing}"
            )

        if self._guard_hooks.session_owner_matcher is None:
            raise ValueError(
                "CodexSessionQueryJSONRPCApplication missing required interrupt ownership "
                "hook: session_owner_matcher"
            )

    async def handle_requests(self, request: Request) -> Response:
        request_id: str | int | None = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                request_id = body.get("id")
                if request_id is not None and not isinstance(request_id, str | int):
                    request_id = None
            base_request = JSONRPCRequestModel.model_validate(body)
        except Exception:
            return await super().handle_requests(request)

        if base_request.method not in self._supported_method_set:
            if base_request.id is None:
                return Response(status_code=204)
            return self._unsupported_method_response(base_request.id, base_request.method)

        if not self._method_registry.is_extension_method(base_request.method):
            return await super().handle_requests(request)

        params = base_request.params or {}
        if not isinstance(params, dict):
            return self._generate_error_response(
                base_request.id,
                InvalidParamsError(message="params must be an object"),
            )

        if base_request.method in self._method_registry.session_query_methods:
            return await handle_session_query_request(self, base_request, params)
        if base_request.method in self._method_registry.session_control_methods:
            return await handle_session_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.discovery_query_methods:
            return await handle_discovery_query_request(self, base_request, params)
        if base_request.method in self._method_registry.discovery_control_methods:
            return await handle_discovery_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.thread_lifecycle_control_methods:
            return await handle_thread_lifecycle_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.interrupt_recovery_methods:
            return await handle_interrupt_recovery_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.turn_control_methods:
            return await handle_turn_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.review_control_methods:
            return await handle_review_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        if base_request.method in self._method_registry.exec_control_methods:
            return await handle_exec_control_request(
                self,
                base_request,
                params,
                request=request,
            )
        return await handle_interrupt_callback_request(
            self,
            base_request,
            params,
            request=request,
        )

    def _unsupported_method_response(
        self,
        request_id: str | int,
        method: str,
    ) -> JSONResponse:
        protocol_version = get_current_protocol_version(self._protocol_version)
        return self._generate_error_response(
            request_id,
            JSONRPCError(
                code=-32601,
                message=f"Unsupported method: {method}",
                data={
                    "type": "METHOD_NOT_SUPPORTED",
                    "method": method,
                    "supported_methods": self._supported_methods,
                    "protocol_version": protocol_version,
                },
            ),
        )

    def _generate_error_response(
        self,
        request_id: str | int | None,
        error: Exception | JSONRPCError | A2AError,
    ) -> JSONResponse:
        if isinstance(error, JSONRPCError | A2AError):
            adapted_error: Exception | JSONRPCError | A2AError = adapt_jsonrpc_error(error)
        else:
            adapted_error = error
        return super()._generate_error_response(
            request_id,
            adapted_error,
        )

    def _jsonrpc_success_response(self, request_id: str | int, result: Any) -> JSONResponse:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        )
