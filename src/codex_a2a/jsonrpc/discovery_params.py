from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, ValidationError, field_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    normalize_non_empty_string,
    parse_positive_int,
    strip_optional_string,
)


class SkillsExtraRootsParams(_StrictModel):
    cwd: str
    extra_user_roots: list[str] = Field(
        validation_alias=AliasChoices("extra_user_roots", "extraUserRoots"),
        serialization_alias="extraUserRoots",
    )

    @field_validator("cwd", mode="before")
    @classmethod
    def _validate_cwd(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="request.cwd must be a non-empty string")

    @field_validator("extra_user_roots", mode="before")
    @classmethod
    def _validate_extra_user_roots(cls, value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("request.extra_user_roots must be a non-empty array")
        roots: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("request.extra_user_roots entries must be non-empty strings")
            roots.append(item.strip())
        return roots


class DiscoverySkillsListParams(_StrictModel):
    cwds: list[str] | None = None
    force_reload: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("force_reload", "forceReload"),
        serialization_alias="forceReload",
    )
    per_cwd_extra_user_roots: list[SkillsExtraRootsParams] | None = Field(
        default=None,
        validation_alias=AliasChoices("per_cwd_extra_user_roots", "perCwdExtraUserRoots"),
        serialization_alias="perCwdExtraUserRoots",
    )

    @field_validator("cwds", mode="before")
    @classmethod
    def _validate_cwds(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("cwds must be an array")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("cwds entries must be non-empty strings")
            result.append(item.strip())
        return result


class DiscoveryAppsListParams(_StrictModel):
    cursor: str | None = None
    limit: int | None = None
    thread_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("thread_id", "threadId"),
        serialization_alias="threadId",
    )
    force_refetch: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("force_refetch", "forceRefetch"),
        serialization_alias="forceRefetch",
    )

    @field_validator("cursor", "thread_id", mode="before")
    @classmethod
    def _validate_optional_string(cls, value: Any) -> str | None:
        return strip_optional_string(value)

    @field_validator("limit", mode="before")
    @classmethod
    def _validate_limit(cls, value: Any) -> int | None:
        return parse_positive_int(value, field="limit")


class DiscoveryPluginsListParams(_StrictModel):
    cwds: list[str] | None = None
    force_remote_sync: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("force_remote_sync", "forceRemoteSync"),
        serialization_alias="forceRemoteSync",
    )

    @field_validator("cwds", mode="before")
    @classmethod
    def _validate_cwds(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("cwds must be an array")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("cwds entries must be non-empty strings")
            result.append(item.strip())
        return result


class DiscoveryPluginReadParams(_StrictModel):
    marketplace_path: str = Field(
        validation_alias=AliasChoices("marketplace_path", "marketplacePath"),
        serialization_alias="marketplacePath",
    )
    plugin_name: str = Field(
        validation_alias=AliasChoices("plugin_name", "pluginName"),
        serialization_alias="pluginName",
    )

    @field_validator("marketplace_path", mode="before")
    @classmethod
    def _validate_marketplace_path(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value,
            message="Missing required params.marketplace_path",
        )

    @field_validator("plugin_name", mode="before")
    @classmethod
    def _validate_plugin_name(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value,
            message="Missing required params.plugin_name",
        )


class DiscoveryWatchRequest(_StrictModel):
    events: list[str] | None = None

    @field_validator("events", mode="before")
    @classmethod
    def _validate_events(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("request.events must be a non-empty array")
        events: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("request.events entries must be non-empty strings")
            events.append(item.strip())
        return events


class DiscoveryWatchParams(_StrictModel):
    request: DiscoveryWatchRequest | None = None


def _raise_discovery_validation_error(exc: ValidationError) -> None:
    extra_forbidden = [
        error for error in exc.errors(include_url=False) if error.get("type") == "extra_forbidden"
    ]
    if extra_forbidden:
        raise map_extra_forbidden(extra_forbidden)

    first = exc.errors(include_url=False)[0]
    loc = tuple(first.get("loc", ()))
    field = format_loc(loc)
    message = str(first.get("msg", "Invalid params")).removeprefix("Value error, ")
    if field == "marketplace_path":
        raise JsonRpcParamsValidationError(
            message="Missing required params.marketplace_path",
            data={"type": "MISSING_FIELD", "field": "marketplace_path"},
        )
    if field == "marketplacePath":
        raise JsonRpcParamsValidationError(
            message="Missing required params.marketplace_path",
            data={"type": "INVALID_FIELD", "field": "marketplace_path"},
        )
    if field == "plugin_name":
        raise JsonRpcParamsValidationError(
            message="Missing required params.plugin_name",
            data={"type": "MISSING_FIELD", "field": "plugin_name"},
        )
    if field == "pluginName":
        raise JsonRpcParamsValidationError(
            message="Missing required params.plugin_name",
            data={"type": "INVALID_FIELD", "field": "plugin_name"},
        )
    raise JsonRpcParamsValidationError(
        message=message,
        data={"type": "INVALID_FIELD", "field": field},
    )


def parse_discovery_skills_list_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = DiscoverySkillsListParams.model_validate(params)
    except ValidationError as exc:
        _raise_discovery_validation_error(exc)
    return parsed.model_dump(by_alias=True, exclude_none=True)


def parse_discovery_apps_list_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = DiscoveryAppsListParams.model_validate(params)
    except ValidationError as exc:
        _raise_discovery_validation_error(exc)
    return parsed.model_dump(by_alias=True, exclude_none=True)


def parse_discovery_plugins_list_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = DiscoveryPluginsListParams.model_validate(params)
    except ValidationError as exc:
        _raise_discovery_validation_error(exc)
    return parsed.model_dump(by_alias=True, exclude_none=True)


def parse_discovery_plugin_read_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = DiscoveryPluginReadParams.model_validate(params)
    except ValidationError as exc:
        _raise_discovery_validation_error(exc)
    return parsed.model_dump(by_alias=True, exclude_none=True)


def parse_discovery_watch_params(params: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = DiscoveryWatchParams.model_validate(params)
    except ValidationError as exc:
        _raise_discovery_validation_error(exc)
    return parsed.model_dump(by_alias=True, exclude_none=True)
