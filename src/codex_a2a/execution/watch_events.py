from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def normalize_watch_event_filter(
    request: dict[str, Any] | None,
    *,
    supported_events: Iterable[str],
    allowed_events: Iterable[str] | None = None,
    field_name: str = "request.events",
) -> frozenset[str]:
    supported = tuple(supported_events)
    supported_lookup = frozenset(supported)
    if allowed_events is None:
        allowed = supported
    else:
        allowed = tuple(allowed_events)

    if not isinstance(request, dict):
        return supported_lookup
    raw_events = request.get("events")
    if raw_events is None:
        return supported_lookup
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError(f"{field_name} must be a non-empty array")

    normalized: set[str] = set()
    for item in raw_events:
        if not isinstance(item, str) or item not in supported_lookup:
            allowed_message = ", ".join(allowed)
            raise ValueError(f"{field_name} entries must be one of: {allowed_message}")
        normalized.add(item)
    return frozenset(normalized)
