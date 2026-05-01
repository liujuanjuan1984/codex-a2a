from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError, field_validator
from pydantic_core import ErrorDetails

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    MetadataParams,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    metadata_validation_error,
    normalize_string_enum,
    normalize_validation_message,
    strip_optional_string,
    validate_params_model,
    validate_required_request_id,
)


class _InterruptReplyParams(_StrictModel):
    request_id: str
    metadata: MetadataParams | None = None

    _validate_request_id = field_validator("request_id", mode="before")(
        validate_required_request_id
    )


class PermissionReplyParams(_InterruptReplyParams):
    reply: Literal["once", "always", "reject"]
    message: str | None = None

    @field_validator("reply", mode="before")
    @classmethod
    def _validate_reply(cls, value: Any) -> str:
        return normalize_string_enum(
            value,
            allowed=("once", "always", "reject"),
            invalid_type_message="reply must be a string",
            invalid_value_message="reply must be one of: once, always, reject",
        )

    @field_validator("message", mode="before")
    @classmethod
    def _validate_message(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class QuestionReplyParams(_InterruptReplyParams):
    answers: list[list[str]]

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


class QuestionRejectParams(_InterruptReplyParams):
    pass


class PermissionsReplyParams(_InterruptReplyParams):
    permissions: dict[str, Any]
    scope: Literal["turn", "session"] | None = None

    @field_validator("permissions", mode="before")
    @classmethod
    def _validate_permissions(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("permissions must be an object")
        return value

    @field_validator("scope", mode="before")
    @classmethod
    def _validate_scope(cls, value: Any) -> str | None:
        return normalize_string_enum(
            value,
            allowed=("turn", "session"),
            invalid_value_message="scope must be one of: turn, session",
            allow_none=True,
        )


class ElicitationReplyParams(_InterruptReplyParams):
    action: Literal["accept", "decline", "cancel"]
    content: Any = None

    @field_validator("action", mode="before")
    @classmethod
    def _validate_action(cls, value: Any) -> str:
        return normalize_string_enum(
            value,
            allowed=("accept", "decline", "cancel"),
            invalid_value_message="action must be one of: accept, decline, cancel",
        )

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: Any, info) -> Any:  # noqa: ANN001
        action = info.data.get("action")
        if action in {"decline", "cancel"} and value is not None:
            raise ValueError("content must be null when action is decline or cancel")
        return value


def _field_error_message(
    first_error: ErrorDetails,
    *,
    default: str,
    missing: str | None = None,
) -> str:
    if first_error.get("type") == "missing":
        return missing or default
    return normalize_validation_message(first_error.get("msg"), default=default)


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
        raise JsonRpcParamsValidationError(
            message=_field_error_message(
                first,
                default="reply must be a string",
            ),
            data={"type": "INVALID_FIELD", "field": "reply"},
        )
    if loc == ("message",):
        raise JsonRpcParamsValidationError(
            message="message must be a string",
            data={"type": "INVALID_FIELD", "field": "message"},
        )
    if loc == ("answers",):
        raise JsonRpcParamsValidationError(
            message=_field_error_message(
                first,
                default="answers must be an array",
            ),
            data={"type": "INVALID_FIELD", "field": "answers"},
        )
    if loc == ("permissions",):
        raise JsonRpcParamsValidationError(
            message=_field_error_message(
                first,
                default="permissions must be an object",
            ),
            data={"type": "INVALID_FIELD", "field": "permissions"},
        )
    if loc == ("scope",):
        raise JsonRpcParamsValidationError(
            message="scope must be one of: turn, session",
            data={"type": "INVALID_FIELD", "field": "scope"},
        )
    if loc == ("action",):
        raise JsonRpcParamsValidationError(
            message=_field_error_message(
                first,
                default="action must be one of: accept, decline, cancel",
            ),
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
            message=normalize_validation_message(first.get("msg"), default="Invalid params"),
            data={"type": "INVALID_FIELD", "field": format_loc(loc)},
        )
    raise JsonRpcParamsValidationError(
        message=str(first.get("msg", "Invalid params")),
        data={"type": "INVALID_FIELD"},
    )


def parse_permission_reply_params(params: dict[str, Any]) -> PermissionReplyParams:
    return validate_params_model(
        PermissionReplyParams,
        params,
        on_error=_raise_interrupt_validation_error,
    )


def parse_question_reply_params(params: dict[str, Any]) -> QuestionReplyParams:
    return validate_params_model(
        QuestionReplyParams,
        params,
        on_error=_raise_interrupt_validation_error,
    )


def parse_question_reject_params(params: dict[str, Any]) -> QuestionRejectParams:
    return validate_params_model(
        QuestionRejectParams,
        params,
        on_error=_raise_interrupt_validation_error,
    )


def parse_permissions_reply_params(params: dict[str, Any]) -> PermissionsReplyParams:
    return validate_params_model(
        PermissionsReplyParams,
        params,
        on_error=_raise_interrupt_validation_error,
    )


def parse_elicitation_reply_params(params: dict[str, Any]) -> ElicitationReplyParams:
    return validate_params_model(
        ElicitationReplyParams,
        params,
        on_error=_raise_interrupt_validation_error,
    )
