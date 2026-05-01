from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import httpx
from a2a.server.jsonrpc_models import InternalError, JSONRPCError
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import (
    invalid_params_response,
    upstream_http_error_response,
    upstream_unreachable_response,
)
from codex_a2a.jsonrpc.owner_guard import validate_thread_owner
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError, validate_params_model
from codex_a2a.jsonrpc.request_models import JSONRPCRequestModel as JSONRPCRequest
from codex_a2a.jsonrpc.thread_lifecycle_params import (
    ThreadArchiveControlParams,
    ThreadForkControlParams,
    ThreadMetadataUpdateControlParams,
    ThreadUnarchiveControlParams,
    ThreadWatchControlParams,
    ThreadWatchReleaseControlParams,
    raise_thread_lifecycle_validation_error,
)

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)

ERR_THREAD_NOT_FOUND = -32010
ERR_THREAD_FORBIDDEN = -32011
ERR_WATCH_NOT_FOUND = -32014
ERR_WATCH_FORBIDDEN = -32015


async def handle_thread_lifecycle_control_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
    *,
    request: Request,
) -> Response:
    parsed_params: (
        ThreadForkControlParams
        | ThreadArchiveControlParams
        | ThreadUnarchiveControlParams
        | ThreadMetadataUpdateControlParams
        | ThreadWatchControlParams
        | ThreadWatchReleaseControlParams
    )
    thread_id: str | None = None
    task_id: str | None = None

    model_type = (
        ThreadForkControlParams
        if base_request.method == app._method_thread_fork
        else ThreadArchiveControlParams
        if base_request.method == app._method_thread_archive
        else ThreadUnarchiveControlParams
        if base_request.method == app._method_thread_unarchive
        else ThreadMetadataUpdateControlParams
        if base_request.method == app._method_thread_metadata_update
        else ThreadWatchReleaseControlParams
        if base_request.method == app._method_thread_watch_release
        else ThreadWatchControlParams
    )
    try:
        parsed_params = cast(
            ThreadForkControlParams
            | ThreadArchiveControlParams
            | ThreadUnarchiveControlParams
            | ThreadMetadataUpdateControlParams
            | ThreadWatchControlParams
            | ThreadWatchReleaseControlParams,
            validate_params_model(
                model_type,
                params,
                on_error=raise_thread_lifecycle_validation_error,
            ),
        )
        if isinstance(
            parsed_params,
            (
                ThreadForkControlParams,
                ThreadArchiveControlParams,
                ThreadUnarchiveControlParams,
                ThreadMetadataUpdateControlParams,
            ),
        ):
            thread_id = parsed_params.thread_id
        elif isinstance(parsed_params, ThreadWatchReleaseControlParams):
            task_id = parsed_params.task_id
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    if thread_id is not None:
        owner_error = await validate_thread_owner(
            app,
            request=request,
            request_id=base_request.id,
            thread_id=thread_id,
            error_code=ERR_THREAD_FORBIDDEN,
            error_message="Thread forbidden",
            error_type="THREAD_FORBIDDEN",
        )
        if owner_error is not None:
            return owner_error

    try:
        if isinstance(parsed_params, ThreadWatchControlParams):
            call_context = app._context_builder.build(request)
            result = await app._thread_lifecycle_runtime.start(
                request=(
                    None
                    if parsed_params.request is None
                    else parsed_params.request.model_dump(
                        by_alias=False,
                        exclude_none=True,
                    )
                ),
                context=call_context,
            )
        elif isinstance(parsed_params, ThreadWatchReleaseControlParams):
            call_context = app._context_builder.build(request)
            result = await app._thread_lifecycle_runtime.release(
                task_id=parsed_params.task_id,
                context=call_context,
            )
        elif isinstance(parsed_params, ThreadForkControlParams):
            thread = await app._codex_client.thread_fork(
                parsed_params.thread_id,
                params=(
                    None
                    if parsed_params.request is None
                    else parsed_params.request.model_dump(exclude_none=True)
                ),
            )
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
        elif isinstance(parsed_params, ThreadArchiveControlParams):
            await app._codex_client.thread_archive(parsed_params.thread_id)
            result = {"ok": True, "thread_id": parsed_params.thread_id}
        elif isinstance(parsed_params, ThreadUnarchiveControlParams):
            thread = await app._codex_client.thread_unarchive(parsed_params.thread_id)
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
        else:
            thread = await app._codex_client.thread_metadata_update(
                parsed_params.thread_id,
                params=parsed_params.request.model_dump(
                    by_alias=False,
                    exclude_none=False,
                    exclude_unset=True,
                ),
            )
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status == 404 and thread_id is not None:
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=ERR_THREAD_NOT_FOUND,
                    message="Thread not found",
                    data={"type": "THREAD_NOT_FOUND", "thread_id": thread_id},
                ),
            )
        return upstream_http_error_response(
            app,
            base_request.id,
            upstream_status=upstream_status,
            data={"thread_id": thread_id, "method": base_request.method},
        )
    except httpx.HTTPError:
        return upstream_unreachable_response(
            app,
            base_request.id,
            data={"thread_id": thread_id, "method": base_request.method},
        )
    except LookupError:
        assert task_id is not None
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_WATCH_NOT_FOUND,
                message="Watch not found",
                data={"type": "WATCH_NOT_FOUND", "task_id": task_id},
            ),
        )
    except PermissionError:
        if task_id is not None:
            return app._generate_error_response(
                base_request.id,
                JSONRPCError(
                    code=ERR_WATCH_FORBIDDEN,
                    message="Watch forbidden",
                    data={"type": "WATCH_FORBIDDEN", "task_id": task_id},
                ),
            )
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_THREAD_FORBIDDEN,
                message="Thread forbidden",
                data={"type": "THREAD_FORBIDDEN", "thread_id": thread_id},
            ),
        )
    except Exception as exc:
        logger.exception("Codex thread lifecycle JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            InternalError(message=str(exc)),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
