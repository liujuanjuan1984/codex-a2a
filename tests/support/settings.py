from __future__ import annotations

from typing import Any

from codex_a2a.config import Settings

_UNSET = object()


def _build_test_auth_credentials(overrides: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    explicit_registry = overrides.pop("a2a_static_auth_credentials", _UNSET)
    if explicit_registry is not _UNSET:
        return tuple(explicit_registry)

    credentials: list[dict[str, Any]] = []
    bearer_token = overrides.pop("a2a_bearer_token", "test-token")
    if isinstance(bearer_token, str) and bearer_token.strip():
        credentials.append(
            {
                "id": "test-bearer",
                "scheme": "bearer",
                "token": bearer_token,
                "principal": "automation",
            }
        )

    basic_username = overrides.pop("a2a_basic_auth_username", _UNSET)
    basic_password = overrides.pop("a2a_basic_auth_password", _UNSET)
    if basic_username is _UNSET and basic_password is _UNSET:
        return tuple(credentials)
    if basic_username is _UNSET or basic_password is _UNSET:
        raise ValueError("Test settings basic auth shorthand requires username and password")
    credentials.append(
        {
            "id": "test-basic",
            "scheme": "basic",
            "username": basic_username,
            "password": basic_password,
        }
    )
    return tuple(credentials)


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "a2a_static_auth_credentials": (
            {
                "id": "test-bearer",
                "scheme": "bearer",
                "token": "test-token",
                "principal": "automation",
            },
        ),
        "a2a_database_url": None,
        "a2a_enable_session_shell": True,
        "a2a_enable_turn_control": True,
        "a2a_enable_review_control": True,
        "a2a_enable_exec_control": True,
    }
    auth_credentials = _build_test_auth_credentials(overrides)
    base.update(overrides)
    base["a2a_static_auth_credentials"] = auth_credentials
    return Settings(**base)
