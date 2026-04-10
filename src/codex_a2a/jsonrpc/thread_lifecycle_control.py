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
    invalid_params_response,
)
from codex_a2a.jsonrpc.owner_guard import validate_thread_owner
from codex_a2a.jsonrpc.params import (
    JsonRpcParamsValidationError,
    ThreadArchiveControlParams,
    ThreadForkControlParams,
    ThreadMetadataUpdateControlParams,
    ThreadUnarchiveControlParams,
    ThreadWatchControlParams,
    ThreadWatchReleaseControlParams,
    parse_thread_archive_params,
    parse_thread_fork_params,
    parse_thread_metadata_update_params,
    parse_thread_unarchive_params,
    parse_thread_watch_params,
    parse_thread_watch_release_params,
)

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)

ERR_THREAD_NOT_FOUND = -32010
ERR_THREAD_FORBIDDEN = -32011
ERR_WATCH_NOT_FOUND = -32014
ERR_WATCH_FORBIDDEN = -32015


def _thread_not_found_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    *,
    thread_id: str,
) -> Response:
    return app._generate_error_response(
        request_id,
        JSONRPCError(
            code=ERR_THREAD_NOT_FOUND,
            message="Thread not found",
            data={"type": "THREAD_NOT_FOUND", "thread_id": thread_id},
        ),
    )


def _watch_not_found_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    *,
    task_id: str,
) -> Response:
    return app._generate_error_response(
        request_id,
        JSONRPCError(
            code=ERR_WATCH_NOT_FOUND,
            message="Watch not found",
            data={"type": "WATCH_NOT_FOUND", "task_id": task_id},
        ),
    )


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

    try:
        if base_request.method == app._method_thread_fork:
            parsed_params = parse_thread_fork_params(params)
            thread_id = parsed_params.thread_id
        elif base_request.method == app._method_thread_archive:
            parsed_params = parse_thread_archive_params(params)
            thread_id = parsed_params.thread_id
        elif base_request.method == app._method_thread_unarchive:
            parsed_params = parse_thread_unarchive_params(params)
            thread_id = parsed_params.thread_id
        elif base_request.method == app._method_thread_metadata_update:
            parsed_params = parse_thread_metadata_update_params(params)
            thread_id = parsed_params.thread_id
        elif base_request.method == app._method_thread_watch_release:
            parsed_params = parse_thread_watch_release_params(params)
            task_id = parsed_params.task_id
        else:
            parsed_params = parse_thread_watch_params(params)
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
        if base_request.method == app._method_thread_watch:
            call_context = app._context_builder.build(request)
            watch_params = (
                parsed_params if isinstance(parsed_params, ThreadWatchControlParams) else None
            )
            result = await app._thread_lifecycle_runtime.start(
                request=(
                    None
                    if watch_params is None or watch_params.request is None
                    else watch_params.request.model_dump(by_alias=True, exclude_none=True)
                ),
                context=call_context,
            )
        elif base_request.method == app._method_thread_watch_release:
            call_context = app._context_builder.build(request)
            watch_release_params = (
                parsed_params
                if isinstance(parsed_params, ThreadWatchReleaseControlParams)
                else None
            )
            assert watch_release_params is not None
            result = await app._thread_lifecycle_runtime.release(
                task_id=watch_release_params.task_id,
                context=call_context,
            )
        elif base_request.method == app._method_thread_fork:
            fork_params = (
                parsed_params if isinstance(parsed_params, ThreadForkControlParams) else None
            )
            assert fork_params is not None
            thread = await app._codex_client.thread_fork(
                fork_params.thread_id,
                params=(
                    None
                    if fork_params.request is None
                    else fork_params.request.model_dump(by_alias=True, exclude_none=True)
                ),
            )
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
        elif base_request.method == app._method_thread_archive:
            archive_params = (
                parsed_params if isinstance(parsed_params, ThreadArchiveControlParams) else None
            )
            assert archive_params is not None
            await app._codex_client.thread_archive(archive_params.thread_id)
            result = {"ok": True, "thread_id": archive_params.thread_id}
        elif base_request.method == app._method_thread_unarchive:
            unarchive_params = (
                parsed_params if isinstance(parsed_params, ThreadUnarchiveControlParams) else None
            )
            assert unarchive_params is not None
            thread = await app._codex_client.thread_unarchive(unarchive_params.thread_id)
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
        else:
            metadata_params = (
                parsed_params
                if isinstance(parsed_params, ThreadMetadataUpdateControlParams)
                else None
            )
            assert metadata_params is not None
            thread = await app._codex_client.thread_metadata_update(
                metadata_params.thread_id,
                params=metadata_params.request.model_dump(
                    by_alias=True,
                    exclude_none=False,
                    exclude_unset=True,
                ),
            )
            result = {"ok": True, "thread_id": thread["id"], "thread": thread}
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status == 404 and thread_id is not None:
            return _thread_not_found_response(app, base_request.id, thread_id=thread_id)
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_UPSTREAM_HTTP_ERROR,
                message="Upstream Codex error",
                data={
                    "type": "UPSTREAM_HTTP_ERROR",
                    "thread_id": thread_id,
                    "upstream_status": upstream_status,
                    "method": base_request.method,
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
                    "thread_id": thread_id,
                    "method": base_request.method,
                },
            ),
        )
    except LookupError:
        assert task_id is not None
        return _watch_not_found_response(app, base_request.id, task_id=task_id)
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
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
