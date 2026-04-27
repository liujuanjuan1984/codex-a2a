from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator

from codex_a2a.jsonrpc.params_common import (
    MetadataParams,
    _StrictModel,
    raise_control_validation_error,
    strip_optional_string,
    validate_request_command,
    validate_required_process_id,
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

    _validate_command = field_validator("command", mode="before")(validate_request_command)

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

    _validate_process_id = field_validator("process_id", mode="before")(
        validate_required_process_id
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

    _validate_process_id = field_validator("process_id", mode="before")(
        validate_required_process_id
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

    _validate_process_id = field_validator("process_id", mode="before")(
        validate_required_process_id
    )


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


def parse_exec_start_params(params: dict[str, Any]) -> ExecStartControlParams:
    try:
        return ExecStartControlParams.model_validate(params)
    except ValidationError as exc:
        raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_write_params(params: dict[str, Any]) -> ExecWriteControlParams:
    try:
        return ExecWriteControlParams.model_validate(params)
    except ValidationError as exc:
        raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_resize_params(params: dict[str, Any]) -> ExecResizeControlParams:
    try:
        return ExecResizeControlParams.model_validate(params)
    except ValidationError as exc:
        raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc


def parse_exec_terminate_params(params: dict[str, Any]) -> ExecTerminateControlParams:
    try:
        return ExecTerminateControlParams.model_validate(params)
    except ValidationError as exc:
        raise_control_validation_error(exc)
        raise AssertionError("unreachable") from exc
