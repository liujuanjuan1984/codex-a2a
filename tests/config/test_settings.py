import json
import os
from unittest import mock

import pytest
from pydantic import ValidationError

from codex_a2a import __version__
from codex_a2a.config import Settings


def _registry_env(credentials: list[dict[str, object]] | None = None) -> dict[str, str]:
    if credentials is None:
        credentials = [
            {
                "id": "test-bearer",
                "scheme": "bearer",
                "token": "test-token",
                "principal": "automation",
            }
        ]
    return {"A2A_STATIC_AUTH_CREDENTIALS": json.dumps(credentials)}


def test_settings_missing_required():
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings()
        assert "Configure runtime authentication via A2A_STATIC_AUTH_CREDENTIALS" in str(
            excinfo.value
        )


def test_settings_valid():
    env = {
        **_registry_env(),
        "CODEX_TIMEOUT": "300",
        "CODEX_MODEL_REASONING_EFFORT": "high",
        "CODEX_MODEL_REASONING_SUMMARY": "concise",
        "CODEX_MODEL_VERBOSITY": "medium",
        "CODEX_PROFILE": "coding",
        "CODEX_APPROVAL_POLICY": "on-request",
        "CODEX_SANDBOX_MODE": "workspace-write",
        "CODEX_SANDBOX_WORKSPACE_WRITE_WRITABLE_ROOTS": "/tmp/workspace,/tmp/cache",
        "CODEX_SANDBOX_WORKSPACE_WRITE_NETWORK_ACCESS": "true",
        "CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_SLASH_TMP": "true",
        "CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_TMPDIR_ENV_VAR": "false",
        "CODEX_WEB_SEARCH": "live",
        "CODEX_REVIEW_MODEL": "gpt-5.1",
        "CODEX_WORKSPACE_ROOT": "/tmp/workspace",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
        assert settings.a2a_static_auth_credentials[0].credential_id == "test-bearer"
        assert settings.codex_timeout == 300.0
        assert settings.codex_model_reasoning_effort == "high"
        assert settings.codex_model_reasoning_summary == "concise"
        assert settings.codex_model_verbosity == "medium"
        assert settings.codex_profile == "coding"
        assert settings.codex_approval_policy == "on-request"
        assert settings.codex_sandbox_mode == "workspace-write"
        assert settings.codex_sandbox_workspace_write_writable_roots == [
            "/tmp/workspace",
            "/tmp/cache",
        ]
        assert settings.codex_sandbox_workspace_write_network_access is True
        assert settings.codex_sandbox_workspace_write_exclude_slash_tmp is True
        assert settings.codex_sandbox_workspace_write_exclude_tmpdir_env_var is False
        assert settings.codex_web_search == "live"
        assert settings.codex_review_model == "gpt-5.1"
        assert settings.codex_workspace_root == "/tmp/workspace"
        assert (
            settings.a2a_database_url
            == "sqlite+aiosqlite:////tmp/workspace/.codex-a2a/codex-a2a.db"
        )
        assert settings.a2a_version == __version__


def test_settings_accept_static_auth_registry_without_legacy_credentials() -> None:
    env = {
        "A2A_STATIC_AUTH_CREDENTIALS": json.dumps(
            [
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
                    "capabilities": ["session_shell"],
                },
                {
                    "scheme": "bearer",
                    "token": "token-disabled",
                    "principal": "disabled",
                    "enabled": False,
                },
            ]
        )
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert len(settings.a2a_static_auth_credentials) == 3
    assert settings.a2a_static_auth_credentials[0].credential_id == "bot-alpha"
    assert settings.a2a_static_auth_credentials[0].principal == "automation-alpha"
    assert settings.a2a_static_auth_credentials[1].principal == "ops"
    assert settings.a2a_static_auth_credentials[1].capabilities == ("session_shell",)
    assert settings.a2a_static_auth_credentials[2].enabled is False


def test_settings_reject_registry_without_enabled_credentials() -> None:
    env = {
        "A2A_STATIC_AUTH_CREDENTIALS": json.dumps(
            [
                {
                    "scheme": "bearer",
                    "token": "token-disabled",
                    "principal": "disabled",
                    "enabled": False,
                }
            ]
        )
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()

    assert "A2A_STATIC_AUTH_CREDENTIALS must contain at least one enabled credential" in str(
        excinfo.value
    )


def test_settings_require_principal_for_registry_bearer() -> None:
    env = {
        "A2A_STATIC_AUTH_CREDENTIALS": json.dumps(
            [
                {
                    "scheme": "bearer",
                    "token": "token-alpha",
                }
            ]
        )
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()

    assert "Static bearer credential requires explicit principal" in str(excinfo.value)


def test_settings_reject_explicit_principal_for_registry_basic() -> None:
    env = {
        "A2A_STATIC_AUTH_CREDENTIALS": json.dumps(
            [
                {
                    "scheme": "basic",
                    "username": "ops",
                    "password": "ops-pass",  # pragma: allowlist secret
                    "principal": "operator",
                }
            ]
        )
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()

    assert "Static basic credential does not accept principal" in str(excinfo.value)


def test_settings_default_database_url_falls_back_without_workspace_root() -> None:
    env = _registry_env()
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert settings.a2a_database_url == "sqlite+aiosqlite:///./codex-a2a.db"


def test_settings_enable_turn_control_by_default() -> None:
    env = _registry_env()
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert settings.a2a_enable_turn_control is True


def test_settings_explicit_none_database_url_is_not_replaced_by_dynamic_default() -> None:
    settings = Settings.model_validate(
        {
            "a2a_static_auth_credentials": [
                {
                    "id": "test-bearer",
                    "scheme": "bearer",
                    "token": "test-token",
                    "principal": "automation",
                }
            ],
            "codex_workspace_root": "/tmp/workspace",
            "a2a_database_url": None,
        }
    )

    assert settings.a2a_database_url is None


def test_settings_parse_ops_flags_and_timeouts():
    env = {
        **_registry_env(),
        "A2A_ENABLE_HEALTH_ENDPOINT": "false",
        "A2A_ENABLE_SESSION_SHELL": "false",
        "A2A_ENABLE_TURN_CONTROL": "false",
        "A2A_ENABLE_REVIEW_CONTROL": "false",
        "A2A_ENABLE_EXEC_CONTROL": "false",
        "A2A_CANCEL_ABORT_TIMEOUT_SECONDS": "0.25",
        "A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS": "45",
        "A2A_INTERRUPT_REQUEST_TTL_SECONDS": "90",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
        assert settings.a2a_enable_health_endpoint is False
        assert settings.a2a_enable_session_shell is False
        assert settings.a2a_enable_turn_control is False
        assert settings.a2a_enable_review_control is False
        assert settings.a2a_enable_exec_control is False
        assert settings.a2a_cancel_abort_timeout_seconds == 0.25
        assert settings.a2a_stream_idle_diagnostic_seconds == 45
        assert settings.a2a_interrupt_request_ttl_seconds == 90


def test_settings_parse_task_store_configuration() -> None:
    env = {**_registry_env(), "A2A_DATABASE_URL": "sqlite+aiosqlite:////tmp/tasks.db"}
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert settings.a2a_database_url == "sqlite+aiosqlite:////tmp/tasks.db"


def test_settings_parse_execution_environment_flags() -> None:
    env = {
        **_registry_env(),
        "A2A_EXECUTION_SANDBOX_MODE": "workspace-write",
        "A2A_EXECUTION_SANDBOX_WRITABLE_ROOTS": "/workspace,/tmp/cache",
        "A2A_EXECUTION_NETWORK_ACCESS": "restricted",
        "A2A_EXECUTION_NETWORK_ALLOWED_DOMAINS": "api.openai.com,github.com",
        "A2A_EXECUTION_APPROVAL_POLICY": "on-request",
        "A2A_EXECUTION_APPROVAL_ESCALATION_BEHAVIOR": "per_request",
        "A2A_EXECUTION_WRITE_ACCESS_SCOPE": "configured_roots",
        "A2A_EXECUTION_WRITE_OUTSIDE_WORKSPACE": "true",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
        assert settings.a2a_execution_sandbox_mode == "workspace-write"
        assert settings.a2a_execution_sandbox_writable_roots == ["/workspace", "/tmp/cache"]
        assert settings.a2a_execution_network_access == "restricted"
        assert settings.a2a_execution_network_allowed_domains == [
            "api.openai.com",
            "github.com",
        ]
        assert settings.a2a_execution_approval_policy == "on-request"
        assert settings.a2a_execution_approval_escalation_behavior == "per_request"
        assert settings.a2a_execution_write_access_scope == "configured_roots"
        assert settings.a2a_execution_write_outside_workspace is True


def test_settings_reject_invalid_cancel_abort_timeout():
    env = {**_registry_env(), "A2A_CANCEL_ABORT_TIMEOUT_SECONDS": "-0.1"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings()
    assert "A2A_CANCEL_ABORT_TIMEOUT_SECONDS" in str(excinfo.value)


def test_settings_reject_invalid_interrupt_request_ttl():
    env = {**_registry_env(), "A2A_INTERRUPT_REQUEST_TTL_SECONDS": "0"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings()
    assert "A2A_INTERRUPT_REQUEST_TTL_SECONDS" in str(excinfo.value)


def test_settings_reject_invalid_stream_idle_diagnostic_seconds():
    env = {**_registry_env(), "A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS": "-1"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings()
    assert "A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS" in str(excinfo.value)


def test_settings_reject_invalid_execution_sandbox_mode() -> None:
    env = {**_registry_env(), "A2A_EXECUTION_SANDBOX_MODE": "sandboxed"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()
    assert "A2A_EXECUTION_SANDBOX_MODE" in str(excinfo.value)


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("CODEX_MODEL_REASONING_EFFORT", "ultra"),
        ("CODEX_MODEL_REASONING_SUMMARY", "verbose"),
        ("CODEX_MODEL_VERBOSITY", "max"),
        ("CODEX_APPROVAL_POLICY", "unlessTrusted"),
        ("CODEX_SANDBOX_MODE", "external-sandbox"),
        ("CODEX_WEB_SEARCH", "on"),
    ],
)
def test_settings_reject_invalid_codex_runtime_overrides(env_name: str, env_value: str) -> None:
    env = {**_registry_env(), env_name: env_value}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()
    assert env_name in str(excinfo.value)


def test_settings_parse_a2a_client_transport_and_timeouts() -> None:
    env = {
        **_registry_env(),
        "A2A_CLIENT_TIMEOUT_SECONDS": "41",
        "A2A_CLIENT_CARD_FETCH_TIMEOUT_SECONDS": "7",
        "A2A_CLIENT_USE_CLIENT_PREFERENCE": "true",
        "A2A_CLIENT_BEARER_TOKEN": "peer-token",
        "A2A_CLIENT_BASIC_AUTH": "user:pass",
        "A2A_CLIENT_SUPPORTED_TRANSPORTS": "http-json,json-rpc",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert settings.a2a_client_timeout_seconds == 41.0
    assert settings.a2a_client_card_fetch_timeout_seconds == 7.0
    assert settings.a2a_client_use_client_preference is True
    assert settings.a2a_client_bearer_token == "peer-token"
    assert settings.a2a_client_basic_auth == "user:pass"
    assert settings.a2a_client_supported_transports == ["HTTP+JSON", "JSONRPC"]


def test_settings_accept_pre_encoded_basic_auth() -> None:
    env = {**_registry_env(), "A2A_CLIENT_BASIC_AUTH": "dXNlcjpwYXNz"}
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()

    assert settings.a2a_client_basic_auth == "dXNlcjpwYXNz"


def test_settings_reject_invalid_basic_auth() -> None:
    env = {**_registry_env(), "A2A_CLIENT_BASIC_AUTH": "not-basic-auth"}
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()

    assert "A2A_CLIENT_BASIC_AUTH" in str(excinfo.value)
