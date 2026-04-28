from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from codex_a2a import __version__
from codex_a2a.protocol_versions import (
    SUPPORTED_PROTOCOL_VERSION,
    normalize_protocol_version,
)

_SANDBOX_MODES = {
    "unknown",
    "read-only",
    "workspace-write",
    "danger-full-access",
}
_FILESYSTEM_SCOPES = {
    "unknown",
    "none",
    "workspace_root",
    "workspace_root_or_descendant",
    "configured_roots",
    "full_filesystem",
}
_NETWORK_ACCESS_MODES = {
    "unknown",
    "disabled",
    "enabled",
    "restricted",
}
_APPROVAL_POLICIES = {
    "unknown",
    "never",
    "on-request",
    "on-failure",
    "untrusted-only",
}
_CODEX_APPROVAL_POLICIES = {
    "never",
    "on-request",
    "on-failure",
    "untrusted",
}
_APPROVAL_ESCALATION_BEHAVIORS = {
    "unknown",
    "unavailable",
    "per_request",
    "fallback_only",
    "restricted",
}
_CODEX_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}
_CODEX_REASONING_SUMMARIES = {
    "auto",
    "concise",
    "detailed",
    "none",
}
_CODEX_VERBOSITIES = {
    "low",
    "medium",
    "high",
}
_CODEX_SANDBOX_MODES = {
    "read-only",
    "workspace-write",
    "danger-full-access",
}
_CODEX_WEB_SEARCH_MODES = {
    "disabled",
    "cached",
    "live",
}


def _parse_str_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        return [item.strip() for item in stripped.split(",") if item.strip()]
    if isinstance(value, tuple):
        return list(value)
    return value


def _normalize_client_transport(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"JSONRPC", "JSON-RPC", "JSON_RPC"}:
        return "JSONRPC"
    if normalized in {"HTTP+JSON", "HTTP_JSON", "HTTP-JSON", "HTTPJSON"}:
        return "HTTP+JSON"
    if normalized in {"GRPC"}:
        return "GRPC"
    return normalized


def _normalize_client_transports(value: Any) -> Any:
    if value is None:
        return ["JSONRPC", "HTTP+JSON"]
    if isinstance(value, str):
        raw_values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item).strip() for item in value if str(item).strip()]
    else:
        raise ValueError("A2A_CLIENT_SUPPORTED_TRANSPORTS must be a comma-separated string or list")

    normalized = [_normalize_client_transport(item) for item in raw_values]
    parsed = [transport for transport in normalized if transport]
    for transport in parsed:
        if transport not in {"JSONRPC", "HTTP+JSON", "GRPC"}:
            raise ValueError("A2A_CLIENT_SUPPORTED_TRANSPORTS contains unsupported transport")
    return parsed or ["JSONRPC", "HTTP+JSON"]


def _parse_auth_credentials(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TypeError("Expected a JSON array for static auth credentials.") from exc
        if not isinstance(parsed, list):
            raise TypeError("Expected a JSON array for static auth credentials.")
        return tuple(parsed)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise TypeError("Expected a JSON array or sequence for static auth credentials.")


def _validate_choice(value: str, *, allowed: set[str], env_name: str) -> str:
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{env_name} must be one of: {allowed_values}")
    return value


def _default_a2a_database_url(*, workspace_root: str | None) -> str:
    if isinstance(workspace_root, str) and workspace_root.strip():
        resolved_workspace_root = Path(workspace_root).expanduser().resolve()
        database_path = resolved_workspace_root / ".codex-a2a" / "codex-a2a.db"
        return f"sqlite+aiosqlite:///{database_path.as_posix()}"
    return "sqlite+aiosqlite:///./codex-a2a.db"


StaticAuthScheme = Literal["bearer", "basic"]


class StaticAuthCredentialSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    credential_id: str | None = Field(default=None, alias="id")
    scheme: StaticAuthScheme
    principal: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None
    capabilities: tuple[str, ...] = ()
    enabled: bool = True

    @model_validator(mode="after")
    def validate_shape(self) -> StaticAuthCredentialSettings:
        self.credential_id = self.credential_id.strip() if self.credential_id else None
        self.principal = self.principal.strip() if self.principal else None
        self.token = self.token.strip() if self.token else None
        self.username = self.username.strip() if self.username else None
        self.password = self.password.strip() if self.password else None
        self.capabilities = tuple(
            item.strip() for item in self.capabilities if isinstance(item, str) and item.strip()
        )

        if self.scheme == "bearer":
            if not self.token:
                raise ValueError("Static bearer credential requires token.")
            if self.username or self.password:
                raise ValueError("Static bearer credential does not accept username/password.")
            if self.principal is None:
                raise ValueError(
                    "Static bearer credential requires explicit principal; "
                    "registry bearer principals must not default to automation."
                )
        else:
            if not self.username or not self.password:
                raise ValueError("Static basic credential requires username/password.")
            if self.token:
                raise ValueError("Static basic credential does not accept token.")
            if self.principal is not None:
                raise ValueError(
                    "Static basic credential does not accept principal; "
                    "principal defaults to username."
                )
            self.principal = self.username

        return self


StaticAuthCredentialList = Annotated[
    tuple[StaticAuthCredentialSettings, ...],
    NoDecode,
    BeforeValidator(_parse_auth_credentials),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # Codex settings (app-server mode)
    codex_workspace_root: str | None = Field(
        default=None,
        alias="CODEX_WORKSPACE_ROOT",
    )
    codex_provider_id: str | None = Field(
        default=None,
        alias="CODEX_PROVIDER_ID",
    )
    codex_model_id: str | None = Field(
        default=None,
        alias="CODEX_MODEL_ID",
    )
    codex_agent: str | None = Field(
        default=None,
        alias="CODEX_AGENT",
    )
    codex_variant: str | None = Field(
        default=None,
        alias="CODEX_VARIANT",
    )
    codex_timeout: float = Field(
        default=120.0,
        alias="CODEX_TIMEOUT",
    )
    codex_timeout_stream: float | None = Field(
        default=None,
        alias="CODEX_TIMEOUT_STREAM",
    )
    codex_cli_bin: str = Field(
        default="codex",
        alias="CODEX_CLI_BIN",
    )
    codex_app_server_listen: str = Field(
        default="stdio://",
        alias="CODEX_APP_SERVER_LISTEN",
    )
    codex_model: str = Field(
        default="gpt-5.1-codex",
        alias="CODEX_MODEL",
    )
    codex_model_reasoning_effort: str | None = Field(
        default=None,
        alias="CODEX_MODEL_REASONING_EFFORT",
    )
    codex_profile: str | None = Field(
        default=None,
        alias="CODEX_PROFILE",
    )
    codex_model_reasoning_summary: str | None = Field(
        default=None,
        alias="CODEX_MODEL_REASONING_SUMMARY",
    )
    codex_model_verbosity: str | None = Field(
        default=None,
        alias="CODEX_MODEL_VERBOSITY",
    )
    codex_approval_policy: str | None = Field(
        default=None,
        alias="CODEX_APPROVAL_POLICY",
    )
    codex_sandbox_mode: str | None = Field(
        default=None,
        alias="CODEX_SANDBOX_MODE",
    )
    codex_sandbox_workspace_write_writable_roots: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="CODEX_SANDBOX_WORKSPACE_WRITE_WRITABLE_ROOTS",
    )
    codex_sandbox_workspace_write_network_access: bool | None = Field(
        default=None,
        alias="CODEX_SANDBOX_WORKSPACE_WRITE_NETWORK_ACCESS",
    )
    codex_sandbox_workspace_write_exclude_slash_tmp: bool | None = Field(
        default=None,
        alias="CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_SLASH_TMP",
    )
    codex_sandbox_workspace_write_exclude_tmpdir_env_var: bool | None = Field(
        default=None,
        alias="CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_TMPDIR_ENV_VAR",
    )
    codex_web_search: str | None = Field(
        default=None,
        alias="CODEX_WEB_SEARCH",
    )
    codex_review_model: str | None = Field(
        default=None,
        alias="CODEX_REVIEW_MODEL",
    )

    # A2A settings
    a2a_public_url: str = Field(default="http://127.0.0.1:8000", alias="A2A_PUBLIC_URL")
    a2a_project: str | None = Field(default=None, alias="A2A_PROJECT")
    a2a_title: str = Field(default="Codex A2A", alias="A2A_TITLE")
    a2a_description: str = Field(default="A2A wrapper service for Codex", alias="A2A_DESCRIPTION")
    a2a_version: str = Field(default=__version__, alias="A2A_VERSION")
    a2a_protocol_version: str = Field(default="1.0", alias="A2A_PROTOCOL_VERSION")
    a2a_enable_health_endpoint: bool = Field(default=True, alias="A2A_ENABLE_HEALTH_ENDPOINT")
    a2a_enable_turn_control: bool = Field(default=True, alias="A2A_ENABLE_TURN_CONTROL")
    a2a_enable_review_control: bool = Field(default=False, alias="A2A_ENABLE_REVIEW_CONTROL")
    a2a_enable_exec_control: bool = Field(default=False, alias="A2A_ENABLE_EXEC_CONTROL")
    a2a_log_level: str = Field(default="WARNING", alias="A2A_LOG_LEVEL")
    a2a_log_payloads: bool = Field(default=False, alias="A2A_LOG_PAYLOADS")
    a2a_log_body_limit: int = Field(default=0, alias="A2A_LOG_BODY_LIMIT")
    a2a_documentation_url: str | None = Field(default=None, alias="A2A_DOCUMENTATION_URL")
    a2a_allow_directory_override: bool = Field(default=True, alias="A2A_ALLOW_DIRECTORY_OVERRIDE")
    a2a_host: str = Field(default="127.0.0.1", alias="A2A_HOST")
    a2a_port: int = Field(default=8000, alias="A2A_PORT")
    a2a_static_auth_credentials: StaticAuthCredentialList = Field(
        default=(),
        alias="A2A_STATIC_AUTH_CREDENTIALS",
    )
    a2a_database_url: str | None = Field(
        default=None,
        alias="A2A_DATABASE_URL",
    )

    # Session cache settings
    a2a_session_cache_ttl_seconds: int = Field(default=3600, alias="A2A_SESSION_CACHE_TTL_SECONDS")
    a2a_session_cache_maxsize: int = Field(default=10_000, alias="A2A_SESSION_CACHE_MAXSIZE")
    a2a_cancel_abort_timeout_seconds: float = Field(
        default=1.0,
        alias="A2A_CANCEL_ABORT_TIMEOUT_SECONDS",
    )
    a2a_stream_idle_diagnostic_seconds: float = Field(
        default=60.0,
        alias="A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS",
    )
    a2a_client_timeout_seconds: float = Field(default=30.0, alias="A2A_CLIENT_TIMEOUT_SECONDS")
    a2a_client_card_fetch_timeout_seconds: float = Field(
        default=5.0,
        alias="A2A_CLIENT_CARD_FETCH_TIMEOUT_SECONDS",
    )
    a2a_client_use_client_preference: bool = Field(
        default=False,
        alias="A2A_CLIENT_USE_CLIENT_PREFERENCE",
    )
    a2a_client_bearer_token: str | None = Field(
        default=None,
        alias="A2A_CLIENT_BEARER_TOKEN",
    )
    a2a_client_basic_auth: str | None = Field(
        default=None,
        alias="A2A_CLIENT_BASIC_AUTH",
    )
    a2a_client_supported_transports: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["JSONRPC", "HTTP+JSON"],
        alias="A2A_CLIENT_SUPPORTED_TRANSPORTS",
    )
    a2a_interrupt_request_ttl_seconds: int = Field(
        default=3600,
        alias="A2A_INTERRUPT_REQUEST_TTL_SECONDS",
    )
    a2a_execution_sandbox_mode: str = Field(
        default="unknown",
        alias="A2A_EXECUTION_SANDBOX_MODE",
    )
    a2a_execution_sandbox_filesystem_scope: str | None = Field(
        default=None,
        alias="A2A_EXECUTION_SANDBOX_FILESYSTEM_SCOPE",
    )
    a2a_execution_sandbox_writable_roots: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="A2A_EXECUTION_SANDBOX_WRITABLE_ROOTS",
    )
    a2a_execution_network_access: str = Field(
        default="unknown",
        alias="A2A_EXECUTION_NETWORK_ACCESS",
    )
    a2a_execution_network_allowed_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="A2A_EXECUTION_NETWORK_ALLOWED_DOMAINS",
    )
    a2a_execution_approval_policy: str = Field(
        default="unknown",
        alias="A2A_EXECUTION_APPROVAL_POLICY",
    )
    a2a_execution_approval_escalation_behavior: str | None = Field(
        default=None,
        alias="A2A_EXECUTION_APPROVAL_ESCALATION_BEHAVIOR",
    )
    a2a_execution_write_access_scope: str | None = Field(
        default=None,
        alias="A2A_EXECUTION_WRITE_ACCESS_SCOPE",
    )
    a2a_execution_write_outside_workspace: bool | None = Field(
        default=None,
        alias="A2A_EXECUTION_WRITE_OUTSIDE_WORKSPACE",
    )

    @field_validator("a2a_cancel_abort_timeout_seconds")
    @classmethod
    def validate_cancel_abort_timeout_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError("A2A_CANCEL_ABORT_TIMEOUT_SECONDS must be >= 0")
        return value

    @field_validator("a2a_stream_idle_diagnostic_seconds")
    @classmethod
    def validate_stream_idle_diagnostic_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS must be > 0")
        return value

    @field_validator("a2a_interrupt_request_ttl_seconds")
    @classmethod
    def validate_interrupt_request_ttl_seconds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("A2A_INTERRUPT_REQUEST_TTL_SECONDS must be >= 1")
        return value

    @field_validator(
        "codex_sandbox_workspace_write_writable_roots",
        "a2a_execution_sandbox_writable_roots",
        "a2a_execution_network_allowed_domains",
        mode="before",
    )
    @classmethod
    def parse_execution_lists(cls, value: Any) -> Any:
        return _parse_str_list(value)

    @field_validator("a2a_protocol_version")
    @classmethod
    def validate_a2a_protocol_version(cls, value: str) -> str:
        normalized = normalize_protocol_version(value)
        if normalized != SUPPORTED_PROTOCOL_VERSION:
            raise ValueError("A2A_PROTOCOL_VERSION must stay on the 1.0 protocol line")
        return normalized

    @field_validator("a2a_execution_sandbox_mode")
    @classmethod
    def validate_execution_sandbox_mode(cls, value: str) -> str:
        return _validate_choice(
            value,
            allowed=_SANDBOX_MODES,
            env_name="A2A_EXECUTION_SANDBOX_MODE",
        )

    @field_validator("codex_model_reasoning_effort")
    @classmethod
    def validate_codex_model_reasoning_effort(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_REASONING_EFFORTS,
            env_name="CODEX_MODEL_REASONING_EFFORT",
        )

    @field_validator("codex_model_reasoning_summary")
    @classmethod
    def validate_codex_model_reasoning_summary(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_REASONING_SUMMARIES,
            env_name="CODEX_MODEL_REASONING_SUMMARY",
        )

    @field_validator("codex_model_verbosity")
    @classmethod
    def validate_codex_model_verbosity(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_VERBOSITIES,
            env_name="CODEX_MODEL_VERBOSITY",
        )

    @field_validator("codex_approval_policy")
    @classmethod
    def validate_codex_approval_policy(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_APPROVAL_POLICIES,
            env_name="CODEX_APPROVAL_POLICY",
        )

    @field_validator("codex_sandbox_mode")
    @classmethod
    def validate_codex_sandbox_mode(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_SANDBOX_MODES,
            env_name="CODEX_SANDBOX_MODE",
        )

    @field_validator("codex_web_search")
    @classmethod
    def validate_codex_web_search(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_CODEX_WEB_SEARCH_MODES,
            env_name="CODEX_WEB_SEARCH",
        )

    @field_validator("a2a_execution_sandbox_filesystem_scope")
    @classmethod
    def validate_execution_sandbox_filesystem_scope(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_FILESYSTEM_SCOPES,
            env_name="A2A_EXECUTION_SANDBOX_FILESYSTEM_SCOPE",
        )

    @field_validator("a2a_execution_network_access")
    @classmethod
    def validate_execution_network_access(cls, value: str) -> str:
        return _validate_choice(
            value,
            allowed=_NETWORK_ACCESS_MODES,
            env_name="A2A_EXECUTION_NETWORK_ACCESS",
        )

    @field_validator("a2a_execution_approval_policy")
    @classmethod
    def validate_execution_approval_policy(cls, value: str) -> str:
        return _validate_choice(
            value,
            allowed=_APPROVAL_POLICIES,
            env_name="A2A_EXECUTION_APPROVAL_POLICY",
        )

    @field_validator("a2a_execution_approval_escalation_behavior")
    @classmethod
    def validate_execution_approval_escalation_behavior(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_APPROVAL_ESCALATION_BEHAVIORS,
            env_name="A2A_EXECUTION_APPROVAL_ESCALATION_BEHAVIOR",
        )

    @field_validator("a2a_execution_write_access_scope")
    @classmethod
    def validate_execution_write_access_scope(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_choice(
            value,
            allowed=_FILESYSTEM_SCOPES,
            env_name="A2A_EXECUTION_WRITE_ACCESS_SCOPE",
        )

    @field_validator("a2a_client_supported_transports", mode="before")
    @classmethod
    def parse_a2a_client_supported_transports(cls, value: Any) -> Any:
        return _normalize_client_transports(value)

    @field_validator("a2a_client_timeout_seconds", "a2a_client_card_fetch_timeout_seconds")
    @classmethod
    def validate_a2a_client_timeout_seconds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("A2A_CLIENT_*_TIMEOUT_SECONDS must be > 0")
        return value

    @field_validator("a2a_client_basic_auth")
    @classmethod
    def validate_a2a_client_basic_auth(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from codex_a2a.client.auth import validate_basic_auth

        validate_basic_auth(value)
        return value

    @model_validator(mode="after")
    def apply_dynamic_defaults(self) -> Settings:
        if self.a2a_static_auth_credentials:
            if not any(credential.enabled for credential in self.a2a_static_auth_credentials):
                raise ValueError(
                    "A2A_STATIC_AUTH_CREDENTIALS must contain at least one enabled credential"
                )
        else:
            raise ValueError("Configure runtime authentication via A2A_STATIC_AUTH_CREDENTIALS")
        if "a2a_database_url" not in self.model_fields_set and self.a2a_database_url is None:
            self.a2a_database_url = _default_a2a_database_url(
                workspace_root=self.codex_workspace_root
            )
        return self

    @classmethod
    def from_env(cls) -> Settings:
        settings_cls: type[BaseSettings] = cls
        return cast(Settings, settings_cls())

    @property
    def a2a_supported_protocol_versions(self) -> list[str]:
        return [SUPPORTED_PROTOCOL_VERSION]
