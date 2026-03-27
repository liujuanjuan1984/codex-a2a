from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.types import A2AError, InternalError, JSONRPCError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import (
    ERR_UPSTREAM_HTTP_ERROR,
    ERR_UPSTREAM_UNREACHABLE,
    extract_directory_from_metadata,
    invalid_params_response,
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

    directory, metadata_error = extract_directory_from_metadata(
        app,
        request_id=base_request.id,
        directory=(
            parsed_params.metadata.codex.directory
            if parsed_params.metadata is not None and parsed_params.metadata.codex is not None
            else None
        ),
    )
    if metadata_error is not None:
        return metadata_error

    call_context = app._context_builder.build(request)
    request_payload = parsed_params.request.model_dump(by_alias=True, exclude_none=True)

    try:
        if base_request.method == app._method_exec_start:
            result = await app._exec_runtime.start(
                request=request_payload,
                directory=directory,
                context=call_context,
            )
        elif base_request.method == app._method_exec_write:
            result = await app._exec_runtime.write(
                process_id=str(request_payload["processId"]).strip(),
                delta_base64=request_payload.get("deltaBase64"),
                close_stdin=request_payload.get("closeStdin"),
            )
        elif base_request.method == app._method_exec_resize:
            result = await app._exec_runtime.resize(
                process_id=str(request_payload["processId"]).strip(),
                rows=int(request_payload["rows"]),
                cols=int(request_payload["cols"]),
            )
        else:
            result = await app._exec_runtime.terminate(
                process_id=str(request_payload["processId"]).strip()
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
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_UPSTREAM_HTTP_ERROR,
                message="Upstream Codex error",
                data={
                    "type": "UPSTREAM_HTTP_ERROR",
                    "upstream_status": exc.response.status_code,
                    "process_id": str(request_payload.get("processId", "")).strip(),
                },
            ),
        )
    except httpx.HTTPError:
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_UPSTREAM_UNREACHABLE,
                message="Upstream Codex unreachable",
                data={
                    "type": "UPSTREAM_UNREACHABLE",
                    "process_id": str(request_payload.get("processId", "")).strip(),
                },
            ),
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
