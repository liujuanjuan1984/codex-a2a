from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field, ValidationError, field_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    normalize_non_empty_string,
    validate_non_empty_parts,
    validate_required_thread_id,
)
from codex_a2a.jsonrpc.session_control_params import PromptAsyncPart


class TurnSteerRequestParams(_StrictModel):
    parts: list[PromptAsyncPart]

    _validate_parts = field_validator("parts", mode="before")(validate_non_empty_parts)


class TurnSteerControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    expected_turn_id: str = Field(
        validation_alias=AliasChoices("expected_turn_id", "expectedTurnId"),
        serialization_alias="expectedTurnId",
    )
    request: TurnSteerRequestParams

    _validate_thread_id = field_validator("thread_id", mode="before")(validate_required_thread_id)

    @field_validator("expected_turn_id", mode="before")
    @classmethod
    def _validate_expected_turn_id(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value,
            message="Missing required params.expected_turn_id",
        )


def _raise_turn_control_validation_error(exc: ValidationError) -> None:
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
    if loc in {("expected_turn_id",), ("expectedTurnId",)}:
        raise JsonRpcParamsValidationError(
            message="Missing required params.expected_turn_id",
            data={"type": "MISSING_FIELD", "field": "expected_turn_id"},
        )
    if loc == ("request",):
        raise JsonRpcParamsValidationError(
            message="params.request must be an object",
            data={"type": "INVALID_FIELD", "field": "request"},
        )
    if (
        first.get("type") == "union_tag_invalid"
        and len(loc) == 3
        and loc[:2] == ("request", "parts")
    ):
        item_index = loc[2]
        raise JsonRpcParamsValidationError(
            message="request.parts[].type must be one of: text, image, mention, skill",
            data={"type": "INVALID_FIELD", "field": f"request.parts[{item_index}].type"},
        )
    if message_text == "request.parts must be a non-empty array":
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": "request.parts"},
        )
    if loc:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
    raise JsonRpcParamsValidationError(message=message_text, data={"type": "INVALID_FIELD"})


def parse_turn_steer_params(params: dict[str, Any]) -> TurnSteerControlParams:
    try:
        return TurnSteerControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_turn_control_validation_error(exc)
        raise AssertionError("unreachable") from exc
