from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    strip_optional_string,
)

InterruptRecoveryType = Literal["permission", "question", "permissions", "elicitation"]


class InterruptRecoveryListParams(_StrictModel):
    interrupt_type: InterruptRecoveryType | None = Field(
        default=None,
        validation_alias=AliasChoices("type", "interrupt_type", "interruptType"),
        serialization_alias="type",
    )

    @field_validator("interrupt_type", mode="before")
    @classmethod
    def _validate_interrupt_type(cls, value: Any) -> str | None:
        normalized = strip_optional_string(value)
        if normalized is None:
            return None
        if normalized not in {"permission", "question", "permissions", "elicitation"}:
            raise ValueError("type must be one of: permission, question, permissions, elicitation")
        return normalized


def _raise_interrupt_recovery_validation_error(exc: ValidationError) -> None:
    errors = exc.errors(include_url=False)
    if errors and all(err.get("type") == "extra_forbidden" for err in errors):
        raise map_extra_forbidden(errors)

    first = errors[0]
    loc = tuple(first.get("loc", ()))
    field = format_loc(loc) if loc else "type"
    message_text = str(first.get("msg", "Invalid params")).removeprefix("Value error, ")
    raise JsonRpcParamsValidationError(
        message=message_text,
        data={"type": "INVALID_FIELD", "field": field},
    )


def parse_interrupt_recovery_list_params(params: dict[str, Any]) -> InterruptRecoveryListParams:
    try:
        return InterruptRecoveryListParams.model_validate(params)
    except ValidationError as exc:
        _raise_interrupt_recovery_validation_error(exc)
        raise AssertionError("unreachable") from exc
