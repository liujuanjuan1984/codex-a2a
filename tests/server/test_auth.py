from __future__ import annotations

from base64 import b64encode

from starlette.requests import Request

from codex_a2a.auth import (
    CAPABILITY_EXEC_CONTROL,
    CAPABILITY_TURN_CONTROL,
    AuthenticatedPrincipal,
    authenticate_static_credential,
    build_static_auth_credentials,
    request_has_capability,
)
from tests.support.settings import make_settings


def _request_with_principal(principal: AuthenticatedPrincipal | None) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
        }
    )
    request.state.authenticated_principal = principal
    return request


def test_build_static_auth_credentials_uses_registry_only() -> None:
    registry_settings = make_settings(
        a2a_static_auth_credentials=(
            {
                "id": "bot-alpha",
                "scheme": "bearer",
                "token": "token-alpha",
                "principal": "automation-alpha",
            },
            {
                "scheme": "basic",
                "username": "ops",
                "password": "ops-pass",  # pragma: allowlist secret
            },
        ),
    )
    registry_credentials = build_static_auth_credentials(registry_settings)

    assert len(registry_credentials) == 2
    assert registry_credentials[0].credential_id == "bot-alpha"
    assert registry_credentials[0].principal == "automation-alpha"
    assert registry_credentials[1].principal == "ops"


def test_authenticate_static_credential_supports_bearer_and_basic() -> None:
    settings = make_settings(
        a2a_static_auth_credentials=(
            {
                "id": "bot-alpha",
                "scheme": "bearer",
                "token": "token-alpha",
                "principal": "automation-alpha",
            },
            {
                "id": "ops-basic",
                "scheme": "basic",
                "username": "ops",
                "password": "ops-pass",  # pragma: allowlist secret
                "capabilities": ["exec_control"],
            },
        ),
    )
    credentials = build_static_auth_credentials(settings)

    bearer_principal = authenticate_static_credential(
        credentials=credentials,
        auth_scheme="Bearer",
        auth_value="token-alpha",
    )
    assert bearer_principal is not None
    assert bearer_principal.identity == "automation-alpha"
    assert bearer_principal.credential_id == "bot-alpha"

    basic_principal = authenticate_static_credential(
        credentials=credentials,
        auth_scheme="Basic",
        auth_value=b64encode(b"ops:ops-pass").decode(),
    )
    assert basic_principal is not None
    assert basic_principal.identity == "ops"
    assert basic_principal.capabilities == (CAPABILITY_EXEC_CONTROL,)
    assert basic_principal.credential_id == "ops-basic"


def test_build_static_auth_credentials_assigns_turn_control_to_basic_by_default() -> None:
    settings = make_settings(
        a2a_static_auth_credentials=(
            {
                "scheme": "basic",
                "username": "ops",
                "password": "ops-pass",  # pragma: allowlist secret
            },
        ),
    )

    credentials = build_static_auth_credentials(settings)

    assert credentials[0].capabilities == (
        CAPABILITY_EXEC_CONTROL,
        CAPABILITY_TURN_CONTROL,
    )


def test_request_has_capability_reads_authenticated_principal() -> None:
    request = _request_with_principal(
        AuthenticatedPrincipal(
            identity="ops",
            auth_scheme="basic",
            capabilities=(CAPABILITY_EXEC_CONTROL,),
        )
    )

    assert request_has_capability(request, CAPABILITY_EXEC_CONTROL) is True
    assert request_has_capability(request, CAPABILITY_TURN_CONTROL) is False
