from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator

from codex_a2a.jsonrpc.params_common import (
    JsonRpcParamsValidationError,
    _StrictModel,
    format_loc,
    map_extra_forbidden,
    normalize_non_empty_string,
    strip_optional_string,
)


class ReviewUncommittedChangesTarget(_StrictModel):
    type: Literal["uncommittedChanges"]


class ReviewBaseBranchTarget(_StrictModel):
    type: Literal["baseBranch"]
    branch: str

    @field_validator("branch", mode="before")
    @classmethod
    def _validate_branch(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="target.branch must be a non-empty string")


class ReviewCommitTarget(_StrictModel):
    type: Literal["commit"]
    sha: str
    title: str | None = None

    @field_validator("sha", mode="before")
    @classmethod
    def _validate_sha(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="target.sha must be a non-empty string")

    @field_validator("title", mode="before")
    @classmethod
    def _validate_title(cls, value: Any) -> str | None:
        return strip_optional_string(value)


class ReviewCustomTarget(_StrictModel):
    type: Literal["custom"]
    instructions: str

    @field_validator("instructions", mode="before")
    @classmethod
    def _validate_instructions(cls, value: Any) -> str:
        return normalize_non_empty_string(
            value,
            message="target.instructions must be a non-empty string",
        )


ReviewTarget = Annotated[
    ReviewUncommittedChangesTarget
    | ReviewBaseBranchTarget
    | ReviewCommitTarget
    | ReviewCustomTarget,
    Field(discriminator="type"),
]


class ReviewStartControlParams(_StrictModel):
    thread_id: str = Field(validation_alias=AliasChoices("thread_id", "threadId"))
    delivery: Literal["inline", "detached"] | None = None
    target: ReviewTarget

    @field_validator("thread_id", mode="before")
    @classmethod
    def _validate_thread_id(cls, value: Any) -> str:
        return normalize_non_empty_string(value, message="Missing required params.thread_id")


def _raise_review_control_validation_error(exc: ValidationError) -> None:
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
    if loc == ("target",):
        raise JsonRpcParamsValidationError(
            message="params.target must be an object",
            data={"type": "INVALID_FIELD", "field": "target"},
        )
    if loc == ("delivery",):
        raise JsonRpcParamsValidationError(
            message="delivery must be one of: inline, detached",
            data={"type": "INVALID_FIELD", "field": "delivery"},
        )
    if loc == ("target", "type"):
        raise JsonRpcParamsValidationError(
            message="target.type must be one of: uncommittedChanges, baseBranch, commit, custom",
            data={"type": "INVALID_FIELD", "field": "target.type"},
        )
    if len(loc) >= 3 and loc[0] == "target":
        variant = loc[1]
        leaf = loc[2]
        if variant in {"uncommittedChanges", "baseBranch", "commit", "custom"}:
            normalized_field = f"target.{leaf}"
            if first.get("type") == "missing":
                raise JsonRpcParamsValidationError(
                    message=f"{normalized_field} must be a non-empty string",
                    data={"type": "INVALID_FIELD", "field": normalized_field},
                )
            raise JsonRpcParamsValidationError(
                message=message_text,
                data={"type": "INVALID_FIELD", "field": normalized_field},
            )
    if loc:
        field = format_loc(loc)
        raise JsonRpcParamsValidationError(
            message=message_text,
            data={"type": "INVALID_FIELD", "field": field},
        )
    raise JsonRpcParamsValidationError(message=message_text, data={"type": "INVALID_FIELD"})


def parse_review_start_params(params: dict[str, Any]) -> ReviewStartControlParams:
    try:
        return ReviewStartControlParams.model_validate(params)
    except ValidationError as exc:
        _raise_review_control_validation_error(exc)
        raise AssertionError("unreachable") from exc
