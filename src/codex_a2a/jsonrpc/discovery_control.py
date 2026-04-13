from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from a2a.types import A2AError, InternalError, InvalidParamsError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.discovery_params import parse_discovery_watch_params
from codex_a2a.jsonrpc.errors import invalid_params_response
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)


async def handle_discovery_control_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    try:
        parsed = parse_discovery_watch_params(params)
        call_context = app._context_builder.build(request)
        result = await app._discovery_runtime.start(
            request=parsed.get("request"),
            context=call_context,
        )
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)
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
        logger.exception("Codex discovery control JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
