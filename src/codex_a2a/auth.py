from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from starlette.requests import Request

from codex_a2a.config import Settings

AUTOMATION_PRINCIPAL = "automation"
OPERATOR_PRINCIPAL = "operator"

CAPABILITY_EXEC_CONTROL = "exec_control"
CAPABILITY_TURN_CONTROL = "turn_control"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    identity: str
    auth_scheme: str
    capabilities: tuple[str, ...] = ()
    credential_id: str | None = None


@dataclass(frozen=True)
class StaticAuthCredential:
    auth_scheme: str
    principal: str
    capabilities: tuple[str, ...]
    token: str | None = None
    username: str | None = None
    password: str | None = None
    credential_id: str | None = None


def build_static_auth_credentials(settings: Settings) -> tuple[StaticAuthCredential, ...]:
    credentials: list[StaticAuthCredential] = []
    for entry in settings.a2a_static_auth_credentials:
        if not entry.enabled:
            continue
        capabilities = entry.capabilities or (
            (
                CAPABILITY_EXEC_CONTROL,
                CAPABILITY_TURN_CONTROL,
            )
            if entry.scheme == "basic"
            else ()
        )
        if entry.scheme == "basic":
            principal = entry.username or OPERATOR_PRINCIPAL
        else:
            principal = entry.principal or AUTOMATION_PRINCIPAL
        credentials.append(
            StaticAuthCredential(
                auth_scheme=entry.scheme,
                principal=principal,
                capabilities=tuple(capabilities),
                token=entry.token,
                username=entry.username,
                password=entry.password,
                credential_id=entry.credential_id,
            )
        )
    return tuple(credentials)


def has_configured_auth_scheme(settings: Settings, scheme: str) -> bool:
    normalized = scheme.strip().lower()
    return any(
        credential.auth_scheme == normalized
        for credential in build_static_auth_credentials(settings)
    )


def authenticate_static_credential(
    *,
    credentials: tuple[StaticAuthCredential, ...],
    auth_scheme: str,
    auth_value: str,
) -> AuthenticatedPrincipal | None:
    normalized_scheme = auth_scheme.lower()
    if normalized_scheme == "bearer":
        for credential in credentials:
            if credential.auth_scheme != "bearer" or credential.token is None:
                continue
            if auth_value == credential.token:
                return AuthenticatedPrincipal(
                    identity=credential.principal,
                    auth_scheme="bearer",
                    capabilities=credential.capabilities,
                    credential_id=credential.credential_id,
                )
        return None

    if normalized_scheme != "basic":
        return None

    try:
        decoded = base64.b64decode(auth_value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    if not username or not password:
        return None
    for credential in credentials:
        if credential.auth_scheme != "basic":
            continue
        if credential.username == username and credential.password == password:
            return AuthenticatedPrincipal(
                identity=credential.principal,
                auth_scheme="basic",
                capabilities=credential.capabilities,
                credential_id=credential.credential_id,
            )
    return None


def request_has_capability(request: Request, capability: str) -> bool:
    principal = getattr(request.state, "authenticated_principal", None)
    if not isinstance(principal, AuthenticatedPrincipal):
        return False
    return capability in principal.capabilities
