from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import httpx
from a2a.types import A2AError, InternalError, JSONRPCRequest
from starlette.requests import Request
from starlette.responses import Response

from codex_a2a.jsonrpc.errors import (
    ERR_INTERRUPT_NOT_FOUND,
    extract_directory_from_params_metadata,
    interrupt_error_response,
    interrupt_expected_type,
    invalid_params_response,
    upstream_http_error_response,
    upstream_unreachable_response,
)
from codex_a2a.jsonrpc.interrupt_lifecycle import (
    interrupt_error_from_exception,
    resolve_interrupt_binding,
    validate_interrupt_owner,
)
from codex_a2a.jsonrpc.interrupt_params import (
    ElicitationReplyParams,
    PermissionReplyParams,
    PermissionsReplyParams,
    QuestionRejectParams,
    QuestionReplyParams,
    parse_elicitation_reply_params,
    parse_permission_reply_params,
    parse_permissions_reply_params,
    parse_question_reject_params,
    parse_question_reply_params,
)
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError
from codex_a2a.upstream.interrupts import InterruptRequestError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)


async def handle_interrupt_callback_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, object],
    *,
    request: Request,
) -> Response:
    parsed_params: (
        PermissionReplyParams
        | QuestionReplyParams
        | QuestionRejectParams
        | PermissionsReplyParams
        | ElicitationReplyParams
    )
    try:
        if base_request.method == app._method_reply_permission:
            parsed_params = parse_permission_reply_params(params)
        elif base_request.method == app._method_reply_question:
            parsed_params = parse_question_reply_params(params)
        elif base_request.method == app._method_reject_question:
            parsed_params = parse_question_reject_params(params)
        elif base_request.method == app._method_reply_permissions:
            parsed_params = parse_permissions_reply_params(params)
        else:
            parsed_params = parse_elicitation_reply_params(params)
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)

    request_id = parsed_params.request_id
    directory, metadata_error = extract_directory_from_params_metadata(
        app,
        request_id=base_request.id,
        metadata=parsed_params.metadata,
    )
    if metadata_error is not None:
        return metadata_error

    if base_request.method == app._method_reject_question:
        expected_interrupt_type = "question"
    else:
        expected_interrupt_type = interrupt_expected_type(
            base_request.method,
            interrupt_methods_by_type=app._interrupt_methods_by_type,
        )
    binding, binding_error = await resolve_interrupt_binding(
        app,
        request_id=request_id,
        response_id=base_request.id,
        expected_interrupt_type=expected_interrupt_type,
    )
    if binding_error is not None:
        return binding_error

    owner_error = await validate_interrupt_owner(
        app,
        request=request,
        binding=binding,
        request_id=request_id,
        response_id=base_request.id,
    )
    if owner_error is not None:
        return owner_error

    try:
        if base_request.method == app._method_reply_permission:
            permission_params = cast(PermissionReplyParams, parsed_params)
            reply = permission_params.reply
            message = permission_params.message
            await app._codex_client.permission_reply(
                request_id,
                reply=reply,
                message=message,
                directory=directory,
            )
            result: dict[str, object] = {"ok": True, "request_id": request_id, "reply": reply}
        elif base_request.method == app._method_reply_question:
            question_params = cast(QuestionReplyParams, parsed_params)
            answers = question_params.answers
            await app._codex_client.question_reply(
                request_id,
                answers=answers,
                directory=directory,
            )
            result = {"ok": True, "request_id": request_id, "answers": answers}
        elif base_request.method == app._method_reject_question:
            await app._codex_client.question_reject(request_id, directory=directory)
            result = {"ok": True, "request_id": request_id}
        elif base_request.method == app._method_reply_permissions:
            permissions_params = cast(PermissionsReplyParams, parsed_params)
            permissions = permissions_params.permissions
            scope = permissions_params.scope
            await app._codex_client.permissions_reply(
                request_id,
                permissions=permissions,
                scope=scope,
                directory=directory,
            )
            result = {
                "ok": True,
                "request_id": request_id,
                "permissions": permissions,
            }
            if scope is not None:
                result["scope"] = scope
        else:
            elicitation_params = cast(ElicitationReplyParams, parsed_params)
            action = elicitation_params.action
            content = elicitation_params.content
            await app._codex_client.elicitation_reply(
                request_id,
                action=action,
                content=content,
                directory=directory,
            )
            result = {
                "ok": True,
                "request_id": request_id,
                "action": action,
            }
            if "content" in elicitation_params.model_fields_set:
                result["content"] = content
    except InterruptRequestError as exc:
        return interrupt_error_from_exception(app, base_request.id, exc)
    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status == 404:
            await app._codex_client.discard_interrupt_request(request_id)
            return interrupt_error_response(
                app,
                base_request.id,
                code=ERR_INTERRUPT_NOT_FOUND,
                message="Interrupt request not found",
                data={"type": "INTERRUPT_REQUEST_NOT_FOUND", "request_id": request_id},
            )
        return upstream_http_error_response(
            app,
            base_request.id,
            upstream_status=upstream_status,
            data={"request_id": request_id},
        )
    except httpx.HTTPError:
        return upstream_unreachable_response(
            app,
            base_request.id,
            data={"request_id": request_id},
        )
    except Exception as exc:
        logger.exception("Codex interrupt callback JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
