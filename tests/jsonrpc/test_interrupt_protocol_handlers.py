import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from a2a.server.jsonrpc_models import JSONRPCError
from a2a.utils.errors import A2AError
from fastapi.responses import JSONResponse

from codex_a2a.jsonrpc.errors import adapt_jsonrpc_error
from codex_a2a.jsonrpc.interrupt_recovery import handle_interrupt_recovery_request
from codex_a2a.jsonrpc.interrupts import handle_interrupt_callback_request
from codex_a2a.jsonrpc.request_models import JSONRPCRequestModel
from codex_a2a.upstream.interrupts import InterruptRequestBinding
from tests.support.dummy_clients import DummySessionQueryCodexClient
from tests.support.jsonrpc_errors import error_context, error_reason
from tests.support.settings import make_settings


def _json_body(response) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


def _build_app(
    codex_client,
    *,
    directory_resolver=None,
    session_owner_matcher=None,
):
    def generate_error_response(request_id, error):
        adapted = (
            adapt_jsonrpc_error(error)
            if isinstance(error, (JSONRPCError, A2AError))
            else error
        )
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": adapted.code,
                "message": adapted.message,
            },
        }
        if getattr(adapted, "data", None) is not None:
            payload["error"]["data"] = adapted.data
        return JSONResponse(payload)

    def success_response(request_id, result):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})

    method_reply_permission = "a2a.interrupt.permission.reply"
    method_reply_question = "a2a.interrupt.question.reply"
    method_reject_question = "a2a.interrupt.question.reject"
    method_reply_permissions = "a2a.interrupt.permissions.reply"
    method_reply_elicitation = "a2a.interrupt.elicitation.reply"
    return SimpleNamespace(
        _codex_client=codex_client,
        _generate_error_response=generate_error_response,
        _jsonrpc_success_response=success_response,
        _method_reply_permission=method_reply_permission,
        _method_reply_question=method_reply_question,
        _method_reject_question=method_reject_question,
        _method_reply_permissions=method_reply_permissions,
        _method_reply_elicitation=method_reply_elicitation,
        _interrupt_methods_by_type={
            "permission": method_reply_permission,
            "question": method_reply_question,
            "permissions": method_reply_permissions,
            "elicitation": method_reply_elicitation,
        },
        _guard_hooks=SimpleNamespace(
            directory_resolver=directory_resolver,
            session_owner_matcher=session_owner_matcher,
        ),
    )


def _build_request(*, user_identity=None, user_credential_id=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_identity=user_identity,
            user_credential_id=user_credential_id,
        )
    )


@pytest.mark.asyncio
async def test_handle_interrupt_callback_permission_reply_returns_success_contract() -> None:
    client = DummySessionQueryCodexClient(make_settings(a2a_bearer_token="test"))
    client._interrupt_requests["perm-1"] = InterruptRequestBinding(
        request_id="perm-1",
        interrupt_type="permission",
        session_id="sess-1",
        created_at=0.0,
    )
    app = _build_app(client, directory_resolver=lambda directory: f"{directory}/resolved")

    response = await handle_interrupt_callback_request(
        app,
        JSONRPCRequestModel(jsonrpc="2.0", id=11, method=app._method_reply_permission),
        {
            "request_id": "perm-1",
            "reply": "always",
            "message": "approved",
            "metadata": {"codex": {"directory": "/workspace/demo"}},
        },
        request=_build_request(),
    )

    assert response.status_code == 200
    assert _json_body(response) == {
        "jsonrpc": "2.0",
        "id": 11,
        "result": {
            "ok": True,
            "request_id": "perm-1",
            "reply": "always",
        },
    }
    assert client.permission_reply_calls == [
        {
            "request_id": "perm-1",
            "reply": "always",
            "message": "approved",
            "directory": "/workspace/demo/resolved",
        }
    ]


@pytest.mark.asyncio
async def test_handle_interrupt_callback_elicitation_reply_preserves_explicit_content() -> None:
    client = DummySessionQueryCodexClient(make_settings(a2a_bearer_token="test"))
    client._interrupt_requests["eli-1"] = InterruptRequestBinding(
        request_id="eli-1",
        interrupt_type="elicitation",
        session_id="sess-2",
        created_at=0.0,
    )
    app = _build_app(client)

    response = await handle_interrupt_callback_request(
        app,
        JSONRPCRequestModel(jsonrpc="2.0", id="rpc-eli", method=app._method_reply_elicitation),
        {
            "request_id": "eli-1",
            "action": "accept",
            "content": {"selection": "yes"},
        },
        request=_build_request(),
    )

    assert response.status_code == 200
    assert _json_body(response)["result"] == {
        "ok": True,
        "request_id": "eli-1",
        "action": "accept",
        "content": {"selection": "yes"},
    }
    assert client.elicitation_reply_calls == [
        {
            "request_id": "eli-1",
            "action": "accept",
            "content": {"selection": "yes"},
            "directory": None,
        }
    ]


@pytest.mark.asyncio
async def test_handle_interrupt_callback_404_discards_request_and_uses_not_found_shape() -> None:
    binding = InterruptRequestBinding(
        request_id="perm-404",
        interrupt_type="permission",
        session_id="sess-404",
        created_at=0.0,
    )
    request = httpx.Request("POST", "http://test/interrupt")
    response_404 = httpx.Response(404, request=request)
    client = SimpleNamespace(
        resolve_interrupt_request=AsyncMock(return_value=("active", binding)),
        permission_reply=AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "missing interrupt",
                request=request,
                response=response_404,
            )
        ),
        discard_interrupt_request=AsyncMock(),
    )
    app = _build_app(client)

    response = await handle_interrupt_callback_request(
        app,
        JSONRPCRequestModel(jsonrpc="2.0", id=404, method=app._method_reply_permission),
        {
            "request_id": "perm-404",
            "reply": "once",
        },
        request=_build_request(),
    )

    payload = _json_body(response)
    assert response.status_code == 200
    assert payload["error"]["code"] == -32004
    assert error_reason(payload) == "INTERRUPT_REQUEST_NOT_FOUND"
    assert error_context(payload)["request_id"] == "perm-404"
    client.discard_interrupt_request.assert_awaited_once_with("perm-404")


@pytest.mark.asyncio
async def test_handle_interrupt_recovery_filters_identity_inputs_and_returns_items() -> None:
    client = SimpleNamespace(
        list_interrupt_requests=AsyncMock(return_value=[{"request_id": "req-1"}])
    )
    app = _build_app(client)

    response = await handle_interrupt_recovery_request(
        app,
        JSONRPCRequestModel(jsonrpc="2.0", id=21, method="codex.interrupts.list"),
        {"interrupt_type": "question"},
        request=_build_request(user_identity=123, user_credential_id="cred-1"),
    )

    assert response.status_code == 200
    assert _json_body(response) == {
        "jsonrpc": "2.0",
        "id": 21,
        "result": {"items": [{"request_id": "req-1"}]},
    }
    client.list_interrupt_requests.assert_awaited_once_with(
        identity=None,
        credential_id="cred-1",
        interrupt_type="question",
    )


@pytest.mark.asyncio
async def test_handle_interrupt_recovery_notification_returns_no_content() -> None:
    client = SimpleNamespace(
        list_interrupt_requests=AsyncMock(return_value=[{"request_id": "req-2"}])
    )
    app = _build_app(client)

    response = await handle_interrupt_recovery_request(
        app,
        JSONRPCRequestModel(jsonrpc="2.0", id=None, method="codex.interrupts.list"),
        {},
        request=_build_request(user_identity="user-1", user_credential_id="cred-2"),
    )

    assert response.status_code == 204
    assert response.body == b""
    client.list_interrupt_requests.assert_awaited_once_with(
        identity="user-1",
        credential_id="cred-2",
        interrupt_type=None,
    )
