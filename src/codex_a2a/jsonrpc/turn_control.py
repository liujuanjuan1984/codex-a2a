from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from a2a.types import A2AError, InternalError, JSONRPCError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import invalid_params_response
from codex_a2a.jsonrpc.params import (
    JsonRpcParamsValidationError,
    TurnSteerControlParams,
    parse_turn_steer_params,
)
from codex_a2a.upstream.models import CodexRPCError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)

ERR_TURN_NOT_STEERABLE = -32012
ERR_TURN_FORBIDDEN = -32013


async def handle_turn_control_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    try:
        parsed_params: TurnSteerControlParams = parse_turn_steer_params(params)
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
                    code=ERR_TURN_FORBIDDEN,
                    message="Turn forbidden",
                    data={"type": "TURN_FORBIDDEN", "thread_id": thread_id},
                ),
            )

    try:
        result = await app._codex_client.turn_steer(
            thread_id,
            expected_turn_id=parsed_params.expected_turn_id,
            request=parsed_params.request.model_dump(by_alias=True, exclude_none=True),
        )
    except PermissionError:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_TURN_FORBIDDEN,
                message="Turn forbidden",
                data={"type": "TURN_FORBIDDEN", "thread_id": thread_id},
            ),
        )
    except CodexRPCError as exc:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_TURN_NOT_STEERABLE,
                message="Turn not steerable",
                data={
                    "type": "TURN_NOT_STEERABLE",
                    "thread_id": thread_id,
                    "expected_turn_id": parsed_params.expected_turn_id,
                    "upstream_code": exc.code,
                    "detail": str(exc),
                },
            ),
        )
    except Exception as exc:
        logger.exception("Codex turn control JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
