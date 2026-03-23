from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.client.middleware import ClientCallContext


def split_request_metadata(
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    request_metadata: dict[str, Any] = {}
    extra_headers: dict[str, str] = {}
    for key, value in dict(metadata or {}).items():
        if isinstance(key, str) and key.lower() == "authorization":
            if value is not None:
                extra_headers["Authorization"] = str(value)
            continue
        request_metadata[key] = value
    return request_metadata or None, extra_headers or None


def build_call_context(
    extra_headers: Mapping[str, str] | None,
) -> ClientCallContext | None:
    if not extra_headers:
        return None
    return ClientCallContext(state={"headers": dict(extra_headers)})


__all__ = ["build_call_context", "split_request_metadata"]
