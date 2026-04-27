from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.server.jsonrpc_models import JSONRPCError
from starlette.requests import Request
from starlette.responses import Response

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication


async def validate_thread_owner(
    app: CodexSessionQueryJSONRPCApplication,
    *,
    request: Request,
    request_id: str | int | None,
    thread_id: str,
    error_code: int,
    error_message: str,
    error_type: str,
) -> Response | None:
    identity = getattr(request.state, "user_identity", None)
    if (
        not isinstance(identity, str)
        or not identity
        or app._guard_hooks.session_owner_matcher is None
    ):
        return None
    owned = await app._guard_hooks.session_owner_matcher(identity=identity, session_id=thread_id)
    if owned is False:
        return app._generate_error_response(
            request_id,
            JSONRPCError(
                code=error_code,
                message=error_message,
                data={"type": error_type, "thread_id": thread_id},
            ),
        )
    return None
