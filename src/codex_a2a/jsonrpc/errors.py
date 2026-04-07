from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from a2a.types import A2AError, InvalidParamsError, JSONRPCError
from starlette.responses import Response

from codex_a2a.jsonrpc.params import JsonRpcParamsValidationError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

ERR_SESSION_NOT_FOUND = -32001
ERR_SESSION_FORBIDDEN = -32006
ERR_AUTHORIZATION_FORBIDDEN = -32007
ERR_UPSTREAM_UNREACHABLE = -32002
ERR_UPSTREAM_HTTP_ERROR = -32003
ERR_INTERRUPT_NOT_FOUND = -32004
ERR_UPSTREAM_PAYLOAD_ERROR = -32005
ERR_INTERRUPT_EXPIRED = -32007
ERR_INTERRUPT_TYPE_MISMATCH = -32008


def interrupt_expected_type(
    method: str,
    *,
    interrupt_methods_by_type: Mapping[str, str],
) -> str:
    for interrupt_type, method_name in interrupt_methods_by_type.items():
        if method == method_name:
            return interrupt_type
    raise ValueError(f"Unsupported interrupt callback method: {method}")


def invalid_params_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    exc: JsonRpcParamsValidationError,
) -> Response:
    return app._generate_error_response(
        request_id,
        A2AError(root=InvalidParamsError(message=str(exc), data=exc.data)),
    )


def session_forbidden_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    *,
    session_id: str,
) -> Response:
    return app._generate_error_response(
        request_id,
        JSONRPCError(
            code=ERR_SESSION_FORBIDDEN,
            message="Session forbidden",
            data={"type": "SESSION_FORBIDDEN", "session_id": session_id},
        ),
    )


def authorization_forbidden_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    *,
    method: str,
    capability: str,
    required_principal: str | None = None,
    error_code: int = ERR_AUTHORIZATION_FORBIDDEN,
) -> Response:
    data: dict[str, Any] = {
        "type": "AUTHORIZATION_FORBIDDEN",
        "method": method,
        "capability": capability,
    }
    if required_principal is not None:
        data["required_principal"] = required_principal
    return app._generate_error_response(
        request_id,
        JSONRPCError(
            code=error_code,
            message="Authorization forbidden",
            data=data,
        ),
    )


def extract_directory_from_metadata(
    app: CodexSessionQueryJSONRPCApplication,
    *,
    request_id: str | int | None,
    directory: str | None,
) -> tuple[str | None, Response | None]:
    if directory is None:
        return None, None
    try:
        if app._guard_hooks.directory_resolver is None:
            return directory, None
        return app._guard_hooks.directory_resolver(directory), None
    except ValueError as exc:
        return None, app._generate_error_response(
            request_id,
            A2AError(
                root=InvalidParamsError(
                    message=str(exc),
                    data={"type": "INVALID_FIELD", "field": "metadata.codex.directory"},
                )
            ),
        )


def interrupt_error_response(
    app: CodexSessionQueryJSONRPCApplication,
    request_id: str | int | None,
    *,
    code: int,
    message: str,
    data: dict[str, Any],
) -> Response:
    return app._generate_error_response(
        request_id,
        JSONRPCError(
            code=code,
            message=message,
            data=data,
        ),
    )
