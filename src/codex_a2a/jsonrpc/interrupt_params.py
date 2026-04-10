from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError, field_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    MetadataParams,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    metadata_validation_error,
    normalize_non_empty_string,
    strip_optional_string,
)


class PermissionReplyParams(_StrictModel):
    request_id: str
    reply: Literal["once", "always", "reject"]
    message: str | None = None
    metadata: MetadataParams | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.request_id")

    @field_validator("reply", mode="before")
    @classmethod
    def _validate_reply(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("reply must be a string")
        normalized = value.strip().lower()
        if normalized not in {"once", "always", "reject"}:
            raise ValueError("reply must be one of: once, always, reject")
        return normalized

    @field_validator("message", mode="before")
    @classmethod
    def _validate_message(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class QuestionReplyParams(_StrictModel):
    request_id: str
    answers: list[list[str]]
    metadata: MetadataParams | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.request_id")

    @field_validator("answers", mode="before")
    @classmethod
    def _validate_answers(cls, value: Any) -> list[list[str]]:
        if not isinstance(value, list):
            raise ValueError("answers must be an array")
        answers: list[list[str]] = []
        for index, item in enumerate(value):
            if not isinstance(item, list):
                raise ValueError(f"answers[{index}] must be an array of strings")
            parsed_group: list[str] = []
            for option in item:
                if not isinstance(option, str):
                    raise ValueError(f"answers[{index}] must contain only strings")
                normalized = option.strip()
                if normalized:
                    parsed_group.append(normalized)
            answers.append(parsed_group)
        return answers


class QuestionRejectParams(_StrictModel):
    request_id: str
    metadata: MetadataParams | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.request_id")


class PermissionsReplyParams(_StrictModel):
    request_id: str
    permissions: dict[str, Any]
    scope: Literal["turn", "session"] | None = None
    metadata: MetadataParams | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.request_id")

    @field_validator("permissions", mode="before")
    @classmethod
    def _validate_permissions(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("permissions must be an object")
        return value

    @field_validator("scope", mode="before")
    @classmethod
    def _validate_scope(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("scope must be one of: turn, session")
        normalized = value.strip().lower()
        if normalized not in {"turn", "session"}:
            raise ValueError("scope must be one of: turn, session")
        return normalized


class ElicitationReplyParams(_StrictModel):
    request_id: str
    action: Literal["accept", "decline", "cancel"]
    content: Any = None
    metadata: MetadataParams | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.request_id")

    @field_validator("action", mode="before")
    @classmethod
    def _validate_action(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("action must be one of: accept, decline, cancel")
        normalized = value.strip().lower()
        if normalized not in {"accept", "decline", "cancel"}:
            raise ValueError("action must be one of: accept, decline, cancel")
        return normalized

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: Any, info) -> Any:  # noqa: ANN001
        action = info.data.get("action")
        if action in {"decline", "cancel"} and value is not None:
            raise ValueError("content must be null when action is decline or cancel")
        return value


def _raise_interrupt_validation_error(exc: ValidationError) -> None:
    errors = exc.errors(include_url=False)
    if errors and all(err.get("type") == "extra_forbidden" for err in errors):
        raise map_extra_forbidden(errors)

    first = errors[0]
    loc = tuple(first.get("loc", ()))
    if loc == ("request_id",):
        raise JsonRpcParamsValidationError(
            message="Missing required params.request_id",
            data={"type": "MISSING_FIELD", "field": "request_id"},
        )
    if loc == ("reply",):
        message = str(first.get("msg", "reply must be a string")).removeprefix("Value error, ")
        if first.get("type") == "missing":
            message = "reply must be a string"
        raise JsonRpcParamsValidationError(
            message=message,
            data={"type": "INVALID_FIELD", "field": "reply"},
        )
    if loc == ("message",):
        raise JsonRpcParamsValidationError(
            message="message must be a string",
            data={"type": "INVALID_FIELD", "field": "message"},
        )
    if loc == ("answers",):
        message = str(first.get("msg", "answers must be an array")).removeprefix("Value error, ")
        if first.get("type") == "missing":
            message = "answers must be an array"
        raise JsonRpcParamsValidationError(
            message=message,
            data={"type": "INVALID_FIELD", "field": "answers"},
        )
    if loc == ("permissions",):
        message = str(first.get("msg", "permissions must be an object")).removeprefix(
            "Value error, "
        )
        if first.get("type") == "missing":
            message = "permissions must be an object"
        raise JsonRpcParamsValidationError(
            message=message,
            data={"type": "INVALID_FIELD", "field": "permissions"},
        )
    if loc == ("scope",):
        raise JsonRpcParamsValidationError(
            message="scope must be one of: turn, session",
            data={"type": "INVALID_FIELD", "field": "scope"},
        )
    if loc == ("action",):
        message = str(first.get("msg", "action must be one of: accept, decline, cancel"))
        message = message.removeprefix("Value error, ")
        if first.get("type") == "missing":
            message = "action must be one of: accept, decline, cancel"
        raise JsonRpcParamsValidationError(
            message=message,
            data={"type": "INVALID_FIELD", "field": "action"},
        )
    if loc == ("content",):
        raise JsonRpcParamsValidationError(
            message="content must be null when action is decline or cancel",
            data={"type": "INVALID_FIELD", "field": "content"},
        )
    if (metadata_error := metadata_validation_error(loc)) is not None:
        raise metadata_error
    if loc:
        raise JsonRpcParamsValidationError(
            message=str(first.get("msg", "Invalid params")).removeprefix("Value error, "),
            data={"type": "INVALID_FIELD", "field": format_loc(loc)},
        )
    raise JsonRpcParamsValidationError(
        message=str(first.get("msg", "Invalid params")),
        data={"type": "INVALID_FIELD"},
    )


def parse_permission_reply_params(params: dict[str, Any]) -> PermissionReplyParams:
    try:
        return PermissionReplyParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_question_reply_params(params: dict[str, Any]) -> QuestionReplyParams:
    try:
        return QuestionReplyParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_question_reject_params(params: dict[str, Any]) -> QuestionRejectParams:
    try:
        return QuestionRejectParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_permissions_reply_params(params: dict[str, Any]) -> PermissionsReplyParams:
    try:
        return PermissionsReplyParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_elicitation_reply_params(params: dict[str, Any]) -> ElicitationReplyParams:
    try:
        return ElicitationReplyParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_validation_error(exc)
        raise AssertionError("unreachable") from exc
