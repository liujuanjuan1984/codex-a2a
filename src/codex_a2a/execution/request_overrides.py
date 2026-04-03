from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})
_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed", "none"})
_PERSONALITIES = frozenset({"none", "friendly", "pragmatic"})


class RequestExecutionOptionsValidationError(ValueError):
    def __init__(self, *, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _normalize_optional_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestExecutionOptionsValidationError(
            field=field,
            message=f"{field} must be a string",
        )
    normalized = value.strip()
    if not normalized:
        raise RequestExecutionOptionsValidationError(
            field=field,
            message=f"{field} must be a non-empty string",
        )
    return normalized


def _normalize_choice(
    value: Any,
    *,
    field: str,
    allowed: frozenset[str],
) -> str | None:
    normalized = _normalize_optional_string(value, field=field)
    if normalized is None:
        return None
    if normalized not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise RequestExecutionOptionsValidationError(
            field=field,
            message=f"{field} must be one of: {allowed_values}",
        )
    return normalized


@dataclass(frozen=True)
class RequestExecutionOptions:
    model: str | None = None
    effort: str | None = None
    summary: str | None = None
    personality: str | None = None

    def is_empty(self) -> bool:
        return (
            self.model is None
            and self.effort is None
            and self.summary is None
            and self.personality is None
        )


def build_request_execution_options(
    *,
    model: Any = None,
    effort: Any = None,
    summary: Any = None,
    personality: Any = None,
    field_prefix: str,
) -> RequestExecutionOptions:
    return RequestExecutionOptions(
        model=_normalize_optional_string(model, field=f"{field_prefix}.model"),
        effort=_normalize_choice(
            effort,
            field=f"{field_prefix}.effort",
            allowed=_REASONING_EFFORTS,
        ),
        summary=_normalize_choice(
            summary,
            field=f"{field_prefix}.summary",
            allowed=_REASONING_SUMMARIES,
        ),
        personality=_normalize_choice(
            personality,
            field=f"{field_prefix}.personality",
            allowed=_PERSONALITIES,
        ),
    )


def request_execution_options_fields() -> list[str]:
    return ["model", "effort", "summary", "personality"]
