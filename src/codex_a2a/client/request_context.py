from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.client import ClientCallContext

from codex_a2a.protocol_versions import ADVERTISED_PROTOCOL_VERSION

from .auth import encode_basic_auth
from .extension_negotiation import merge_extension_service_parameters, parse_requested_extensions


def build_default_headers(
    bearer_token: str | None,
    basic_auth: str | None = None,
) -> dict[str, str]:
    headers = {"A2A-Version": ADVERTISED_PROTOCOL_VERSION}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    elif basic_auth:
        headers["Authorization"] = f"Basic {encode_basic_auth(basic_auth)}"
    return headers


def split_request_metadata(
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, tuple[str, ...] | None]:
    request_metadata: dict[str, Any] = {}
    extra_headers: dict[str, str] = {}
    requested_extensions: list[str] = []
    for key, value in dict(metadata or {}).items():
        if isinstance(key, str) and key.lower() == "authorization":
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("Authorization metadata header must be a string")
                extra_headers["Authorization"] = value
            continue
        if isinstance(key, str) and key.lower() == "a2a-version":
            raise ValueError(
                f"A2A-Version is fixed to {ADVERTISED_PROTOCOL_VERSION} and must not be overridden"
            )
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
    *,
    default_headers: Mapping[str, str] | None = None,
) -> ClientCallContext | None:
    merged_headers = dict(default_headers or {})
    if extra_headers:
        merged_headers.update(extra_headers)
    service_parameters = merge_extension_service_parameters(merged_headers, extensions)
    if not service_parameters:
        return None
    return ClientCallContext(service_parameters=service_parameters)
