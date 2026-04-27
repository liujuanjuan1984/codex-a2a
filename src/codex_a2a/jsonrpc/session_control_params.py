from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    MetadataParams,
    _PermissiveModel,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    metadata_validation_error,
    normalize_non_empty_string,
    strip_optional_string,
    validate_non_empty_parts,
    validate_request_command,
    validate_required_session_id,
)


class PromptTextPart(_PermissiveModel):
    type: Literal["text"]
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def _validate_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("request.parts[].text must be a string")
        return value


class PromptImagePart(_PermissiveModel):
    type: Literal["image"]
    url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("url", "image_url", "imageUrl"),
    )
    bytes: str | None = None
    mime_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mime_type", "mimeType"),
        serialization_alias="mimeType",
    )
    name: str | None = None

    @field_validator("url", "bytes", "mime_type", "name", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)

    @model_validator(mode="after")
    def _require_url_or_bytes(self) -> PromptImagePart:
        if self.url is None and self.bytes is None:
            raise ValueError("request.parts[].url or request.parts[].bytes is required")
        if self.bytes is not None and self.mime_type is None and self.url is None:
            raise ValueError("request.parts[].mimeType is required when bytes is provided")
        return self


class PromptMentionPart(_PermissiveModel):
    type: Literal["mention"]
    name: str
    path: str

    @field_validator("name", "path", mode="before")
    @classmethod
    def _validate_strings(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="must be a non-empty string")


class PromptSkillPart(_PermissiveModel):
    type: Literal["skill"]
    name: str
    path: str

    @field_validator("name", "path", mode="before")
    @classmethod
    def _validate_strings(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="must be a non-empty string")


PromptAsyncPart = Annotated[
    PromptTextPart | PromptImagePart | PromptMentionPart | PromptSkillPart,
    Field(discriminator="type"),
]


class PromptAsyncRequestParams(_StrictModel):
    parts: list[PromptAsyncPart]
    message_id: str | None = Field(
        default=None,
        validation_alias="messageID",
        serialization_alias="messageID",
    )
    agent: str | None = None
    system: str | None = None
    variant: str | None = None

    _validate_parts = field_validator("parts", mode="before")(validate_non_empty_parts)

    @field_validator("message_id", "agent", "system", "variant", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class CommandRequestParams(_StrictModel):
    command: str
    arguments: str | None = None
    message_id: str | None = Field(
        default=None,
        validation_alias="messageID",
        serialization_alias="messageID",
    )

    _validate_command = field_validator("command", mode="before")(validate_request_command)

    @field_validator("arguments", "message_id", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class ShellRequestParams(_StrictModel):
    command: str

    _validate_command = field_validator("command", mode="before")(validate_request_command)


class PromptAsyncControlParams(_StrictModel):
    session_id: str
    request: PromptAsyncRequestParams
    metadata: MetadataParams | None = None

    _validate_session_id = field_validator("session_id", mode="before")(
        validate_required_session_id
    )


class CommandControlParams(_StrictModel):
    session_id: str
    request: CommandRequestParams
    metadata: MetadataParams | None = None

    _validate_session_id = field_validator("session_id", mode="before")(
        validate_required_session_id
    )


class ShellControlParams(_StrictModel):
    session_id: str
    request: ShellRequestParams
    metadata: MetadataParams | None = None

    _validate_session_id = field_validator("session_id", mode="before")(
        validate_required_session_id
    )


def _raise_control_validation_error(exc: ValidationError) -> None:
    errors = exc.errors(include_url=False)
    if errors and all(err.get("type") == "extra_forbidden" for err in errors):
        raise map_extra_forbidden(errors)

    first = errors[0]
    loc = tuple(first.get("loc", ()))
    message_text = str(first.get("msg", "Invalid params")).removeprefix("Value error, ")
    if message_text == "request.rows and request.cols must be provided together":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.cols"},
        )
    if message_text == "request.parts[].url or request.parts[].bytes is required":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.parts"},
        )
    if message_text == "request.parts[].mimeType is required when bytes is provided":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.parts"},
        )
    if message_text == "request.delta_base64 or request.close_stdin=true is required":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.close_stdin"},
        )
    if loc == ("session_id",):
        raise JsonRpcParamsValidationError(
            message="Missing required params.session_id",
            data={"type": "MISSING_FIELD", "field": "session_id"},
        )
    if loc == ("request",):
        raise JsonRpcParamsValidationError(
            message="params.request must be an object",
            data={"type": "INVALID_FIELD", "field": "request"},
        )
    if loc == ("request", "parts"):
        raise JsonRpcParamsValidationError(
            message="request.parts must be a non-empty array",
            data={"type": "INVALID_FIELD", "field": "request.parts"},
        )
    if loc == ("request", "command"):
        raise JsonRpcParamsValidationError(
            message="request.command must be a non-empty string",
            data={"type": "INVALID_FIELD", "field": "request.command"},
        )
    if loc == ("request", "processId") or loc == ("request", "process_id"):
        raise JsonRpcParamsValidationError(
            message="request.process_id must be a non-empty string",
            data={"type": "INVALID_FIELD", "field": "request.process_id"},
        )
    if (metadata_error := metadata_validation_error(loc, message_text=message_text)) is not None:
        raise metadata_error
    if loc in {
        ("request", "arguments"),
        ("request", "messageID"),
        ("request", "agent"),
        ("request", "system"),
        ("request", "variant"),
        ("request", "processId"),
        ("request", "process_id"),
        ("request", "deltaBase64"),
        ("request", "delta_base64"),
    }:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a string",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if (
        len(loc) >= 3
        and loc[:2] == ("request", "parts")
        and loc[-1] in {"url", "bytes", "mimeType", "mime_type", "name", "path"}
    ):
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a string",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if loc in {
        ("request", "rows"),
        ("request", "cols"),
        ("request", "outputBytesCap"),
        ("request", "output_bytes_cap"),
        ("request", "timeoutMs"),
        ("request", "timeout_ms"),
    }:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a positive integer",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if loc in {
        ("request", "tty"),
        ("request", "disableOutputCap"),
        ("request", "disable_output_cap"),
        ("request", "disableTimeout"),
        ("request", "disable_timeout"),
        ("request", "closeStdin"),
        ("request", "close_stdin"),
    }:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a boolean",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if len(loc) >= 3 and loc[:2] == ("request", "parts") and loc[-1] == "text":
        field = format_loc(loc)
        if field.endswith(".text.text"):
            field = field.removesuffix(".text")
        raise JsonRpcParamsValidationError(
            message=f"{field} must be a string",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if (
        first.get("type") == "union_tag_invalid"
        and len(loc) >= 3
        and loc[:2] == ("request", "parts")
    ):
        field = f"{format_loc(loc)}.type"
        raise JsonRpcParamsValidationError(
            message="request.parts[].type must be one of: text, image, mention, skill",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if len(loc) >= 3 and loc[:2] == ("request", "parts") and loc[-1] == "type":
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message="request.parts[].type must be one of: text, image, mention, skill",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if len(loc) >= 2 and loc[:2] == ("request", "parts") and loc[-1] != "type":
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=f"{field} must be an object",
            data={"type": "INVALID_FIELD", "field": field},
        )
    if loc:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
    raise JsonRpcParamsValidationError(
        message=message_text,
        data={"type": "INVALID_FIELD"},
    )


def parse_prompt_async_params(params: dict[str, Any]) -> PromptAsyncControlParams:
    try:
        return PromptAsyncControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_command_params(params: dict[str, Any]) -> CommandControlParams:
    try:
        return CommandControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_shell_params(params: dict[str, Any]) -> ShellControlParams:
    try:
        return ShellControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc
