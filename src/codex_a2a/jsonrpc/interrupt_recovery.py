from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import invalid_params_response
from codex_a2a.jsonrpc.interrupt_recovery_params import (
    InterruptRecoveryListParams,
    parse_interrupt_recovery_list_params,
)
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError
from codex_a2a.jsonrpc.request_models import JSONRPCRequestModel as JSONRPCRequest

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication


async def handle_interrupt_recovery_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    try:
        parsed_params: InterruptRecoveryListParams = parse_interrupt_recovery_list_params(params)
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    identity = getattr(request.state, "user_identity", None)
    credential_id = getattr(request.state, "user_credential_id", None)
    items = await app._codex_client.list_interrupt_requests(
        identity=identity if isinstance(identity, str) else None,
        credential_id=credential_id if isinstance(credential_id, str) else None,
        interrupt_type=parsed_params.interrupt_type,
    )
    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, {"items": items})
