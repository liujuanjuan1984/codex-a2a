from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from a2a.types import A2AError, InternalError, InvalidParamsError, JSONRPCError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import invalid_params_response
from codex_a2a.jsonrpc.params import (
    JsonRpcParamsValidationError,
    ReviewStartControlParams,
    ReviewWatchControlParams,
    parse_review_start_params,
    parse_review_watch_params,
)
from codex_a2a.upstream.models import CodexRPCError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)

ERR_REVIEW_FORBIDDEN = -32016
ERR_REVIEW_REJECTED = -32017


async def handle_review_control_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    try:
        if base_request.method == app._method_review_watch:
            parsed_params: ReviewStartControlParams | ReviewWatchControlParams = (
                parse_review_watch_params(params)
            )
        else:
            parsed_params = parse_review_start_params(params)
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    thread_id = parsed_params.thread_id
    identity = getattr(request.state, "user_identity", None)
    if (
        isinstance(identity, str)
        and identity
        and app._guard_hooks.session_owner_matcher is not None
    ):
        owned = await app._guard_hooks.session_owner_matcher(
            identity=identity, session_id=thread_id
        )
        if owned is False:
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=ERR_REVIEW_FORBIDDEN,
                    message="Review forbidden",
                    data={"type": "REVIEW_FORBIDDEN", "thread_id": thread_id},
                ),
            )

    try:
        if base_request.method == app._method_review_watch:
            watch_params = (
                parsed_params if isinstance(parsed_params, ReviewWatchControlParams) else None
            )
            assert watch_params is not None
            call_context = app._context_builder.build(request)
            result = await app._review_runtime.start(
                thread_id=watch_params.thread_id,
                review_thread_id=watch_params.review_thread_id,
                turn_id=watch_params.turn_id,
                request=(
                    None
                    if watch_params.request is None
                    else watch_params.request.model_dump(by_alias=True, exclude_none=True)
                ),
                context=call_context,
            )
        else:
            start_params = (
                parsed_params if isinstance(parsed_params, ReviewStartControlParams) else None
            )
            assert start_params is not None
            result = await app._codex_client.review_start(
                thread_id,
                target=start_params.target.model_dump(by_alias=True, exclude_none=True),
                delivery=start_params.delivery,
            )
    except PermissionError:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_REVIEW_FORBIDDEN,
                message="Review forbidden",
                data={"type": "REVIEW_FORBIDDEN", "thread_id": thread_id},
            ),
        )
    except CodexRPCError as exc:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_REVIEW_REJECTED,
                message="Review request rejected",
                data={
                    "type": "REVIEW_REJECTED",
                    "thread_id": thread_id,
                    "upstream_code": exc.code,
                    "detail": str(exc),
                },
            ),
        )
    except ValueError as exc:
        return app._generate_error_response(
            base_request.id,
            A2AError(
                root=InvalidParamsError(
                    message=str(exc),
                    data={"type": "INVALID_FIELD", "field": "request.events"},
                ),
            ),
        )
    except Exception as exc:
        logger.exception("Codex review control JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
