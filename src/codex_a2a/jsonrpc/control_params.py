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
    normalize_non_empty_string,
    strip_optional_string,
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

    @field_validator("parts", mode="before")
    @classmethod
    def _validate_parts(cls, value: Any) -> Any:
        if not isinstance(value, list) or not value:
            raise ValueError("request.parts must be a non-empty array")
        return value

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

    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="request.command must be a non-empty string"
        )

    @field_validator("arguments", "message_id", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class ShellRequestParams(_StrictModel):
    command: str

    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="request.command must be a non-empty string"
        )


class ExecStartRequestParams(_StrictModel):
    command: str
    arguments: str | None = None
    process_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("process_id", "processId"),
        serialization_alias="processId",
    )
    tty: bool = True
    rows: int | None = None
    cols: int | None = None
    output_bytes_cap: int | None = Field(
        default=None,
        validation_alias=AliasChoices("output_bytes_cap", "outputBytesCap"),
        serialization_alias="outputBytesCap",
    )
    disable_output_cap: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("disable_output_cap", "disableOutputCap"),
        serialization_alias="disableOutputCap",
    )
    timeout_ms: int | None = Field(
        default=None,
        validation_alias=AliasChoices("timeout_ms", "timeoutMs"),
        serialization_alias="timeoutMs",
    )
    disable_timeout: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("disable_timeout", "disableTimeout"),
        serialization_alias="disableTimeout",
    )

    @field_validator("command", mode="before")
    @classmethod
    def _validate_command(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="request.command must be a non-empty string"
        )

    @field_validator("arguments", "process_id", mode="before")
    @classmethod
    def _validate_optional_strings(cls, value: Any) -> str | None:
        return strip_optional_string(value)

    @field_validator("rows", "cols", "output_bytes_cap", "timeout_ms", mode="before")
    @classmethod
    def _validate_optional_positive_ints(cls, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("must be a positive integer")
        return value

    @field_validator("disable_output_cap", "disable_timeout", "tty", mode="before")
    @classmethod
    def _validate_bools(cls, value: Any) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("must be a boolean")
        return value

    @model_validator(mode="after")
    def _validate_size_pair(self) -> ExecStartRequestParams:
        if (self.rows is None) ^ (self.cols is None):
            raise ValueError("request.rows and request.cols must be provided together")
        return self


class ExecWriteRequestParams(_StrictModel):
    process_id: str = Field(
        validation_alias=AliasChoices("process_id", "processId"),
        serialization_alias="processId",
    )
    delta_base64: str | None = Field(
        default=None,
        validation_alias=AliasChoices("delta_base64", "deltaBase64"),
        serialization_alias="deltaBase64",
    )
    close_stdin: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("close_stdin", "closeStdin"),
        serialization_alias="closeStdin",
    )

    @field_validator("process_id", mode="before")
    @classmethod
    def _validate_process_id(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="Missing required params.request.process_id"
        )

    @field_validator("delta_base64", mode="before")
    @classmethod
    def _validate_delta_base64(cls, value: Any) -> str | None:
        return strip_optional_string(value)

    @field_validator("close_stdin", mode="before")
    @classmethod
    def _validate_close_stdin(cls, value: Any) -> bool | None:
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError("request.close_stdin must be a boolean")
        return value

    @model_validator(mode="after")
    def _require_payload(self) -> ExecWriteRequestParams:
        if self.delta_base64 is None and self.close_stdin is not True:
            raise ValueError("request.delta_base64 or request.close_stdin=true is required")
        return self


class ExecResizeRequestParams(_StrictModel):
    process_id: str = Field(
        validation_alias=AliasChoices("process_id", "processId"),
        serialization_alias="processId",
    )
    rows: int
    cols: int

    @field_validator("process_id", mode="before")
    @classmethod
    def _validate_process_id(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="Missing required params.request.process_id"
        )

    @field_validator("rows", "cols", mode="before")
    @classmethod
    def _validate_positive_ints(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("must be a positive integer")
        return value


class ExecTerminateRequestParams(_StrictModel):
    process_id: str = Field(
        validation_alias=AliasChoices("process_id", "processId"),
        serialization_alias="processId",
    )

    @field_validator("process_id", mode="before")
    @classmethod
    def _validate_process_id(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value, message="Missing required params.request.process_id"
        )


class PromptAsyncControlParams(_StrictModel):
    session_id: str
    request: PromptAsyncRequestParams
    metadata: MetadataParams | None = None

    @field_validator("session_id", mode="before")
    @classmethod
    def _validate_session_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.session_id")


class CommandControlParams(_StrictModel):
    session_id: str
    request: CommandRequestParams
    metadata: MetadataParams | None = None

    @field_validator("session_id", mode="before")
    @classmethod
    def _validate_session_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.session_id")


class ShellControlParams(_StrictModel):
    session_id: str
    request: ShellRequestParams
    metadata: MetadataParams | None = None

    @field_validator("session_id", mode="before")
    @classmethod
    def _validate_session_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.session_id")


class ExecStartControlParams(_StrictModel):
    request: ExecStartRequestParams
    metadata: MetadataParams | None = None


class ExecWriteControlParams(_StrictModel):
    request: ExecWriteRequestParams
    metadata: MetadataParams | None = None


class ExecResizeControlParams(_StrictModel):
    request: ExecResizeRequestParams
    metadata: MetadataParams | None = None


class ExecTerminateControlParams(_StrictModel):
    request: ExecTerminateRequestParams
    metadata: MetadataParams | None = None


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
    if loc == ("metadata",):
        raise JsonRpcParamsValidationError(
            message="metadata must be an object",
            data={"type": "INVALID_FIELD", "field": "metadata"},
        )
    if loc == ("metadata", "codex"):
        raise JsonRpcParamsValidationError(
            message="metadata.codex must be an object",
            data={"type": "INVALID_FIELD", "field": "metadata.codex"},
        )
    if loc == ("metadata", "codex", "directory"):
        raise JsonRpcParamsValidationError(
            message="metadata.codex.directory must be a string",
            data={"type": "INVALID_FIELD", "field": "metadata.codex.directory"},
        )
    if loc == ("metadata", "codex", "execution"):
        raise JsonRpcParamsValidationError(
            message="metadata.codex.execution must be an object",
            data={"type": "INVALID_FIELD", "field": "metadata.codex.execution"},
        )
    if loc in {
        ("metadata", "codex", "execution", "model"),
        ("metadata", "codex", "execution", "effort"),
        ("metadata", "codex", "execution", "summary"),
        ("metadata", "codex", "execution", "personality"),
    }:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
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
        and loc[-1]
        in {
            "url",
            "bytes",
            "mimeType",
            "mime_type",
            "name",
            "path",
        }
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
            message=("request.parts[].type must be one of: text, image, mention, skill"),
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


def parse_exec_start_params(params: dict[str, Any]) -> ExecStartControlParams:
    try:
        return ExecStartControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_write_params(params: dict[str, Any]) -> ExecWriteControlParams:
    try:
        return ExecWriteControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_resize_params(params: dict[str, Any]) -> ExecResizeControlParams:
    try:
        return ExecResizeControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_terminate_params(params: dict[str, Any]) -> ExecTerminateControlParams:
    try:
        return ExecTerminateControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc
