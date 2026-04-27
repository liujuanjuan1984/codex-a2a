from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.server.jsonrpc_models import InternalError, JSONRPCError
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import (
    ERR_SESSION_NOT_FOUND,
    ERR_UPSTREAM_PAYLOAD_ERROR,
    invalid_params_response,
    upstream_http_error_response,
    upstream_unreachable_response,
)
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError
from codex_a2a.jsonrpc.payload_mapping import (
    as_a2a_message,
    as_a2a_session_task,
    extract_raw_items,
)
from codex_a2a.jsonrpc.query_params import (
    parse_get_session_messages_params,
    parse_list_sessions_params,
)
from codex_a2a.jsonrpc.request_models import JSONRPCRequestModel as JSONRPCRequest
from codex_a2a.upstream.models import CodexRPCError, is_thread_not_found_error

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)


async def handle_session_query_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
) -> Response:
    try:
        if base_request.method == app._method_list_sessions:
            query = parse_list_sessions_params(params)
            session_id: str | None = None
        else:
            session_id, query = parse_get_session_messages_params(params)
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    try:
        if session_id is None:
            raw_result = await app._codex_client.list_sessions(params=query)
        else:
            raw_result = await app._codex_client.list_messages(session_id, params=query)
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status == 404 and base_request.method == app._method_get_session_messages:
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=ERR_SESSION_NOT_FOUND,
                    message="Session not found",
                    data={"type": "SESSION_NOT_FOUND", "session_id": session_id},
                ),
            )
        return upstream_http_error_response(
            app,
            base_request.id,
            upstream_status=upstream_status,
        )
    except httpx.HTTPError:
        return upstream_unreachable_response(
            app,
            base_request.id,
        )
    except CodexRPCError as exc:
        if is_thread_not_found_error(exc) and session_id is not None:
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=ERR_SESSION_NOT_FOUND,
                    message="Session not found",
                    data={"type": "SESSION_NOT_FOUND", "session_id": session_id},
                ),
            )
        logger.exception("Codex session query JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            InternalError(message=str(exc)),
        )
    except Exception as exc:
        logger.exception("Codex session query JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            InternalError(message=str(exc)),
        )

    try:
        if base_request.method == app._method_list_sessions:
            raw_items = extract_raw_items(raw_result, kind="sessions")
        else:
            raw_items = extract_raw_items(raw_result, kind="messages")
    except ValueError as exc:
        logger.warning("Upstream Codex payload mismatch: %s", exc)
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_UPSTREAM_PAYLOAD_ERROR,
                message="Upstream Codex payload mismatch",
                data={"type": "UPSTREAM_PAYLOAD_ERROR", "detail": str(exc)},
            ),
        )

    if base_request.method == app._method_list_sessions:
        items = [task for item in raw_items if (task := as_a2a_session_task(item)) is not None]
    else:
        assert session_id is not None
        items = [
            message
            for item in raw_items
            if (message := as_a2a_message(session_id, item)) is not None
        ]

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, {"items": items})
