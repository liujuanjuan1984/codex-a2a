from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def mapping_value(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def nested_value(root: Mapping[str, Any], *path: str) -> Any:
    current: Any = root
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def first_nested_string(root: Mapping[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = normalized_string(nested_value(root, *path))
        if value is not None:
            return value
    return None


def first_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    return first_nested_string(payload, *((key,) for key in keys))


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = normalized_string(item)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
