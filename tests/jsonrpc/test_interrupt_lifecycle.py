from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from codex_a2a.jsonrpc.errors import (
    ERR_INTERRUPT_EXPIRED,
    ERR_INTERRUPT_NOT_FOUND,
    ERR_INTERRUPT_TYPE_MISMATCH,
)
from codex_a2a.jsonrpc.interrupt_lifecycle import (
    interrupt_error_from_exception,
    resolve_interrupt_binding,
    validate_interrupt_owner,
)
from codex_a2a.upstream.interrupts import InterruptRequestBinding, InterruptRequestError


def _build_app(
    *,
    interrupt_result: tuple[str, InterruptRequestBinding | None] = ("active", None),
    owner_matcher: AsyncMock | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        _codex_client=SimpleNamespace(
            resolve_interrupt_request=AsyncMock(return_value=interrupt_result)
        ),
        _guard_hooks=SimpleNamespace(session_owner_matcher=owner_matcher),
        _generate_error_response=MagicMock(
            side_effect=lambda request_id, error: {
                "request_id": request_id,
                "error": error,
            }
        ),
    )


@pytest.mark.asyncio
async def test_resolve_interrupt_binding_returns_not_found_error() -> None:
    app = _build_app(interrupt_result=("missing", None))

    binding, response = await resolve_interrupt_binding(
        app,
        request_id="req-1",
        response_id="rpc-1",
        expected_interrupt_type="permissions",
    )

    assert binding is None
    assert response is not None
    assert response["request_id"] == "rpc-1"
    assert response["error"].code == ERR_INTERRUPT_NOT_FOUND
    assert response["error"].data == {
        "type": "INTERRUPT_REQUEST_NOT_FOUND",
        "request_id": "req-1",
    }


@pytest.mark.asyncio
async def test_resolve_interrupt_binding_returns_expired_error() -> None:
    app = _build_app(interrupt_result=("expired", None))

    binding, response = await resolve_interrupt_binding(
        app,
        request_id="req-2",
        response_id="rpc-2",
        expected_interrupt_type="permissions",
    )

    assert binding is None
    assert response is not None
    assert response["error"].code == ERR_INTERRUPT_EXPIRED
    assert response["error"].data == {
        "type": "INTERRUPT_REQUEST_EXPIRED",
        "request_id": "req-2",
    }


@pytest.mark.asyncio
async def test_resolve_interrupt_binding_rejects_type_mismatch() -> None:
    binding = InterruptRequestBinding(
        request_id="req-3",
        interrupt_type="question",
        session_id="sess-1",
        created_at=10.0,
    )
    app = _build_app(interrupt_result=("active", binding))

    resolved_binding, response = await resolve_interrupt_binding(
        app,
        request_id="req-3",
        response_id="rpc-3",
        expected_interrupt_type="permissions",
    )

    assert resolved_binding is None
    assert response is not None
    assert response["error"].code == ERR_INTERRUPT_TYPE_MISMATCH
    assert response["error"].data == {
        "type": "INTERRUPT_TYPE_MISMATCH",
        "request_id": "req-3",
        "expected_interrupt_type": "permissions",
        "actual_interrupt_type": "question",
    }


@pytest.mark.asyncio
async def test_resolve_interrupt_binding_returns_active_binding() -> None:
    binding = InterruptRequestBinding(
        request_id="req-4",
        interrupt_type="permissions",
        session_id="sess-2",
        created_at=10.0,
    )
    app = _build_app(interrupt_result=("active", binding))

    resolved_binding, response = await resolve_interrupt_binding(
        app,
        request_id="req-4",
        response_id="rpc-4",
        expected_interrupt_type="permissions",
    )

    assert resolved_binding == binding
    assert response is None


@pytest.mark.asyncio
async def test_validate_interrupt_owner_hides_foreign_session() -> None:
    owner_matcher = AsyncMock(return_value=False)
    app = _build_app(owner_matcher=owner_matcher)
    binding = InterruptRequestBinding(
        request_id="req-5",
        interrupt_type="permissions",
        session_id="sess-3",
        created_at=10.0,
    )
    request = SimpleNamespace(state=SimpleNamespace(user_identity=" user-1 "))

    response = await validate_interrupt_owner(
        app,
        request=request,
        binding=binding,
        request_id="req-5",
        response_id="rpc-5",
    )

    assert response is not None
    assert response["error"].code == ERR_INTERRUPT_NOT_FOUND
    owner_matcher.assert_awaited_once_with(identity="user-1", session_id="sess-3")


@pytest.mark.asyncio
async def test_validate_interrupt_owner_skips_missing_identity_or_hook() -> None:
    owner_matcher = AsyncMock(return_value=True)
    app = _build_app(owner_matcher=owner_matcher)
    binding = InterruptRequestBinding(
        request_id="req-6",
        interrupt_type="permissions",
        session_id="sess-4",
        created_at=10.0,
    )

    no_identity_response = await validate_interrupt_owner(
        app,
        request=SimpleNamespace(state=SimpleNamespace(user_identity="  ")),
        binding=binding,
        request_id="req-6",
        response_id="rpc-6",
    )
    assert no_identity_response is None

    app_without_matcher = _build_app(owner_matcher=None)
    no_matcher_response = await validate_interrupt_owner(
        app_without_matcher,
        request=SimpleNamespace(state=SimpleNamespace(user_identity="user-2")),
        binding=binding,
        request_id="req-6",
        response_id="rpc-6",
    )
    assert no_matcher_response is None
    owner_matcher.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_interrupt_owner_allows_matching_session() -> None:
    owner_matcher = AsyncMock(return_value=True)
    app = _build_app(owner_matcher=owner_matcher)
    binding = InterruptRequestBinding(
        request_id="req-7",
        interrupt_type="permissions",
        session_id="sess-7",
        created_at=10.0,
    )

    response = await validate_interrupt_owner(
        app,
        request=SimpleNamespace(state=SimpleNamespace(user_identity="user-7")),
        binding=binding,
        request_id="req-7",
        response_id="rpc-7",
    )

    assert response is None
    owner_matcher.assert_awaited_once_with(identity="user-7", session_id="sess-7")


def test_interrupt_error_from_exception_maps_known_error_types() -> None:
    app = _build_app()

    expired = interrupt_error_from_exception(
        app,
        "rpc-8",
        InterruptRequestError(
            error_type="INTERRUPT_REQUEST_EXPIRED",
            request_id="req-8",
        ),
    )
    mismatch = interrupt_error_from_exception(
        app,
        "rpc-9",
        InterruptRequestError(
            error_type="INTERRUPT_TYPE_MISMATCH",
            request_id="req-9",
            expected_interrupt_type="permissions",
            actual_interrupt_type="question",
        ),
    )
    missing = interrupt_error_from_exception(
        app,
        "rpc-10",
        InterruptRequestError(
            error_type="INTERRUPT_REQUEST_NOT_FOUND",
            request_id="req-10",
        ),
    )

    assert expired["error"].code == ERR_INTERRUPT_EXPIRED
    assert expired["error"].data == {
        "type": "INTERRUPT_REQUEST_EXPIRED",
        "request_id": "req-8",
    }
    assert mismatch["error"].code == ERR_INTERRUPT_TYPE_MISMATCH
    assert mismatch["error"].data == {
        "type": "INTERRUPT_TYPE_MISMATCH",
        "request_id": "req-9",
        "expected_interrupt_type": "permissions",
        "actual_interrupt_type": "question",
    }
    assert missing["error"].code == ERR_INTERRUPT_NOT_FOUND
    assert missing["error"].data == {
        "type": "INTERRUPT_REQUEST_NOT_FOUND",
        "request_id": "req-10",
    }
