from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator

from codex_a2a.contracts.extensions import THREAD_LIFECYCLE_SUPPORTED_EVENTS
from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    MetadataParams,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    metadata_validation_error,
    normalize_non_empty_string,
    strip_optional_string,
    validate_required_thread_id,
)


class ThreadForkRequestParams(_StrictModel):
    ephemeral: bool | None = None

    @field_validator("ephemeral", mode="before")
    @classmethod
    def _validate_ephemeral(cls, value: Any) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("request.ephemeral must be a boolean")
        return value


class ThreadGitInfoPatchParams(_StrictModel):
    sha: str | None = None
    branch: str | None = None
    origin_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("origin_url", "originUrl"),
        serialization_alias="originUrl",
    )

    @field_validator("sha", "branch", "origin_url", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> ThreadGitInfoPatchParams:
        if not self.model_fields_set:
            raise ValueError("request.git_info must include at least one field")
        return self


class ThreadMetadataUpdateRequestParams(_StrictModel):
    git_info: ThreadGitInfoPatchParams = Field(
        validation_alias=AliasChoices("git_info", "gitInfo"),
        serialization_alias="gitInfo",
    )


class ThreadWatchRequestParams(_StrictModel):
    events: list[str] | None = None
    thread_ids: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("thread_ids", "threadIds"),
        serialization_alias="threadIds",
    )

    @field_validator("events", mode="before")
    @classmethod
    def _validate_events(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("request.events must be a non-empty array")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or item not in THREAD_LIFECYCLE_SUPPORTED_EVENTS:
                allowed = ", ".join(THREAD_LIFECYCLE_SUPPORTED_EVENTS)
                raise ValueError(f"request.events entries must be one of: {allowed}")
            if item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized

    @field_validator("thread_ids", mode="before")
    @classmethod
    def _validate_thread_ids(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("request.thread_ids must be a non-empty array")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized_item = normalize_non_empty_string(
                item, message="request.thread_ids[] must be a non-empty string"
            )
            if normalized_item in seen:
                continue
            normalized.append(normalized_item)
            seen.add(normalized_item)
        return normalized


class ThreadForkControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    request: ThreadForkRequestParams | None = None
    metadata: MetadataParams | None = None

    _validate_thread_id = field_validator("thread_id", mode="before")(validate_required_thread_id)


class ThreadArchiveControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    metadata: MetadataParams | None = None

    _validate_thread_id = field_validator("thread_id", mode="before")(validate_required_thread_id)


class ThreadUnarchiveControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    metadata: MetadataParams | None = None

    _validate_thread_id = field_validator("thread_id", mode="before")(validate_required_thread_id)


class ThreadMetadataUpdateControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    request: ThreadMetadataUpdateRequestParams
    metadata: MetadataParams | None = None

    _validate_thread_id = field_validator("thread_id", mode="before")(validate_required_thread_id)


class ThreadWatchControlParams(_StrictModel):
    request: ThreadWatchRequestParams | None = None
    metadata: MetadataParams | None = None


class ThreadWatchReleaseControlParams(_StrictModel):
    task_id: str = Field(validation_alias=AliasChoices("task_id", "taskId"))
    metadata: MetadataParams | None = None

    @field_validator("task_id", mode="before")
    @classmethod
    def _validate_task_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.task_id")


def _raise_thread_lifecycle_validation_error(exc: ValidationError) -> None:
    errors = exc.errors(include_url=False)
    if errors and all(err.get("type") == "extra_forbidden" for err in errors):
        raise map_extra_forbidden(errors)

    first = errors[0]
    loc = tuple(first.get("loc", ()))
    message_text = str(first.get("msg", "Invalid params")).removeprefix("Value error, ")

    if loc in {("thread_id",), ("threadId",)}:
        raise JsonRpcParamsValidationError(
            message="Missing required params.thread_id",
            data={"type": "MISSING_FIELD", "field": "thread_id"},
        )
    if loc in {("task_id",), ("taskId",)}:
        raise JsonRpcParamsValidationError(
            message="Missing required params.task_id",
            data={"type": "MISSING_FIELD", "field": "task_id"},
        )
    if loc == ("request",):
        raise JsonRpcParamsValidationError(
            message="params.request must be an object",
            data={"type": "INVALID_FIELD", "field": "request"},
        )
    if (metadata_error := metadata_validation_error(loc)) is not None:
        raise metadata_error
    if message_text == "request.git_info must include at least one field":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.git_info"},
        )
    if message_text in {
        "request.events must be a non-empty array",
        "request.thread_ids must be a non-empty array",
    }:
        field = "request.events" if "events" in message_text else "request.thread_ids"
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
    if message_text.startswith("request.events entries must be one of:"):
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.events"},
        )
    if message_text == "request.ephemeral must be a boolean":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.ephemeral"},
        )
    if loc in {
        ("request", "gitInfo", "sha"),
        ("request", "gitInfo", "branch"),
        ("request", "gitInfo", "originUrl"),
        ("request", "git_info", "sha"),
        ("request", "git_info", "branch"),
        ("request", "git_info", "origin_url"),
    }:
        field = format_loc(loc).replace("gitInfo", "git_info").replace("originUrl", "origin_url")
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a string",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if len(loc) >= 3 and loc[:2] == ("request", "threadIds"):
        raise JsonRpcParamsValidationError(
            message="request.thread_ids[] must be a non-empty string",
            data={"type": "INVALID_FIELD", "field": "request.thread_ids"},
        )
    if loc in {("request", "threadIds"), ("request", "thread_ids")}:
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.thread_ids"},
        )
    if len(loc) >= 3 and loc[:2] == ("request", "thread_ids"):
        raise JsonRpcParamsValidationError(
            message="request.thread_ids[] must be a non-empty string",
            data={"type": "INVALID_FIELD", "field": "request.thread_ids"},
        )
    if loc:
        field = format_loc(loc).replace("gitInfo", "git_info").replace("originUrl", "origin_url")
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
    raise JsonRpcParamsValidationError(message=message_text, data={"type": "INVALID_FIELD"})


def parse_thread_fork_params(params: dict[str, Any]) -> ThreadForkControlParams:
    try:
        return ThreadForkControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_thread_archive_params(params: dict[str, Any]) -> ThreadArchiveControlParams:
    try:
        return ThreadArchiveControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_thread_unarchive_params(params: dict[str, Any]) -> ThreadUnarchiveControlParams:
    try:
        return ThreadUnarchiveControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_thread_metadata_update_params(
    params: dict[str, Any],
) -> ThreadMetadataUpdateControlParams:
    try:
        return ThreadMetadataUpdateControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_thread_watch_params(params: dict[str, Any]) -> ThreadWatchControlParams:
    try:
        return ThreadWatchControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_thread_watch_release_params(params: dict[str, Any]) -> ThreadWatchReleaseControlParams:
    try:
        return ThreadWatchReleaseControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_thread_lifecycle_validation_error(exc)
        raise AssertionError("unreachable") from exc
