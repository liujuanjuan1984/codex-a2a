from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.client import ClientCallContext

from .auth import encode_basic_auth
from .extension_negotiation import merge_extension_service_parameters, parse_requested_extensions


def build_default_headers(
    bearer_token: str | None,
    basic_auth: str | None = None,
) -> dict[str, str]:
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}
    if basic_auth:
        return {"Authorization": f"Basic {encode_basic_auth(basic_auth)}"}
    return {}


def split_request_metadata(
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, tuple[str, ...] | None]:
    request_metadata: dict[str, Any] = {}
    extra_headers: dict[str, str] = {}
    requested_extensions: list[str] = []
    for key, value in dict(metadata or {}).items():
        if isinstance(key, str) and key.lower() == "authorization":
            if value is not None:
                extra_headers["Authorization"] = str(value)
            continue
        if isinstance(key, str) and key.lower() == "a2a-version":
            if value is not None:
                extra_headers["A2A-Version"] = str(value)
            continue
        if isinstance(key, str) and key.lower() == "a2a-extensions":
            if isinstance(value, str):
                requested_extensions.append(value)
            elif isinstance(value, list | tuple | set):
                requested_extensions.extend(
                    str(item) for item in value if isinstance(item, str) and item.strip()
                )
            continue
        request_metadata[key] = value
    return (
        request_metadata or None,
        extra_headers or None,
        parse_requested_extensions(requested_extensions),
    )


def build_call_context(
    extra_headers: Mapping[str, str] | None,
    extensions: tuple[str, ...] | None = None,
) -> ClientCallContext | None:
    service_parameters = merge_extension_service_parameters(extra_headers, extensions)
    if not service_parameters:
        return None
    return ClientCallContext(service_parameters=service_parameters)
