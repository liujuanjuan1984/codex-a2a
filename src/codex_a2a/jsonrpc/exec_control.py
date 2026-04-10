from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.types import A2AError, InternalError, JSONRPCError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.auth import (
    CAPABILITY_EXEC_CONTROL,
    OPERATOR_PRINCIPAL,
    request_has_capability,
)
from codex_a2a.jsonrpc.errors import (
    authorization_forbidden_response,
    extract_directory_from_params_metadata,
    invalid_params_response,
    upstream_http_error_response,
    upstream_unreachable_response,
)
from codex_a2a.jsonrpc.params import (
    ExecResizeControlParams,
    ExecStartControlParams,
    ExecTerminateControlParams,
    ExecWriteControlParams,
    JsonRpcParamsValidationError,
    parse_exec_resize_params,
    parse_exec_start_params,
    parse_exec_terminate_params,
    parse_exec_write_params,
)

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)


ERR_EXEC_SESSION_NOT_FOUND = -32009
ERR_EXEC_FORBIDDEN = -32018


async def handle_exec_control_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    parsed_params: (
        ExecStartControlParams
        | ExecWriteControlParams
        | ExecResizeControlParams
        | ExecTerminateControlParams
    )
    try:
        if base_request.method == app._method_exec_start:
            parsed_params = parse_exec_start_params(params)
        elif base_request.method == app._method_exec_write:
            parsed_params = parse_exec_write_params(params)
        elif base_request.method == app._method_exec_resize:
            parsed_params = parse_exec_resize_params(params)
        else:
            parsed_params = parse_exec_terminate_params(params)
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    directory, metadata_error = extract_directory_from_params_metadata(
        app,
        request_id=base_request.id,
        metadata=parsed_params.metadata,
    )
    if metadata_error is not None:
        return metadata_error

    identity = getattr(request.state, "user_identity", None)
    credential_id = getattr(request.state, "user_credential_id", None)
    if not request_has_capability(request, CAPABILITY_EXEC_CONTROL):
        logger.warning(
            "Exec authorization denied identity=%s credential_id=%s method=%s",
            identity,
            credential_id,
            base_request.method,
        )
        return authorization_forbidden_response(
            app,
            base_request.id,
            method=base_request.method,
            capability=CAPABILITY_EXEC_CONTROL,
            credential_id=credential_id if isinstance(credential_id, str) else None,
            required_principal=OPERATOR_PRINCIPAL,
        )

    call_context = app._context_builder.build(request)
    owner_identity = identity if isinstance(identity, str) and identity else None
    request_payload = parsed_params.request.model_dump(by_alias=True, exclude_none=True)

    try:
        if base_request.method == app._method_exec_start:
            result = await app._exec_runtime.start(
                request=request_payload,
                directory=directory,
                context=call_context,
                owner_identity=owner_identity,
            )
        elif base_request.method == app._method_exec_write:
            result = await app._exec_runtime.write(
                process_id=str(request_payload["processId"]).strip(),
                delta_base64=request_payload.get("deltaBase64"),
                close_stdin=request_payload.get("closeStdin"),
                owner_identity=owner_identity,
            )
        elif base_request.method == app._method_exec_resize:
            result = await app._exec_runtime.resize(
                process_id=str(request_payload["processId"]).strip(),
                rows=int(request_payload["rows"]),
                cols=int(request_payload["cols"]),
                owner_identity=owner_identity,
            )
        else:
            result = await app._exec_runtime.terminate(
                process_id=str(request_payload["processId"]).strip(),
                owner_identity=owner_identity,
            )
    except LookupError as exc:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_EXEC_SESSION_NOT_FOUND,
                message="Exec session not found",
                data={
                    "type": "EXEC_SESSION_NOT_FOUND",
                    "process_id": str(request_payload.get("processId", "")).strip(),
                    "detail": str(exc),
                },
            ),
        )
    except PermissionError:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_EXEC_FORBIDDEN,
                message="Exec session forbidden",
                data={
                    "type": "EXEC_FORBIDDEN",
                    "process_id": str(request_payload.get("processId", "")).strip(),
                },
            ),
        )
    except ValueError as exc:
        if "unique among active exec sessions" in str(exc):
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=-32602,
                    message=str(exc),
                    data={"type": "INVALID_FIELD", "field": "request.process_id"},
                ),
            )
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )
    except httpx.HTTPStatusError as exc:
        process_id = str(request_payload.get("processId", "")).strip()
        return upstream_http_error_response(
            app,
            base_request.id,
            upstream_status=exc.response.status_code,
            data={"process_id": process_id},
        )
    except httpx.HTTPError:
        process_id = str(request_payload.get("processId", "")).strip()
        return upstream_unreachable_response(
            app,
            base_request.id,
            data={"process_id": process_id},
        )
    except Exception as exc:
        logger.exception("Codex exec JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
