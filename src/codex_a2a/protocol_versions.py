from __future__ import annotations

import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

_PROTOCOL_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?$")
_CURRENT_PROTOCOL_VERSION: ContextVar[str | None] = ContextVar(
    "_CURRENT_PROTOCOL_VERSION",
    default=None,
)
SUPPORTED_PROTOCOL_VERSION = "1.0"
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (SUPPORTED_PROTOCOL_VERSION,)
ADVERTISED_PROTOCOL_VERSION = "1.0"
PROVIDER_PRIVATE_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSION

V1_SUPPORTED_FEATURES: tuple[str, ...] = (
    "A2A-Version request-time negotiation and response header echo.",
    "Official A2A 1.0 JSON-RPC methods and /v1 HTTP endpoints.",
    "Unified Part(text|data|url|raw) payloads, task streaming, and protocol-aware error shaping.",
)


class UnsupportedProtocolVersionError(ValueError):
    def __init__(self, requested_version: str) -> None:
        self.requested_version = requested_version
        self.supported_protocol_versions = SUPPORTED_PROTOCOL_VERSIONS
        self.default_protocol_version = ADVERTISED_PROTOCOL_VERSION
        supported_display = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
        super().__init__(
            f"Unsupported A2A protocol version {requested_version!r}. "
            f"Supported versions: {supported_display}."
        )


@dataclass(frozen=True)
class NegotiatedProtocolVersion:
    protocol_version: str
    explicit: bool


def normalize_protocol_version(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Protocol version must be a non-empty string.")
    match = _PROTOCOL_VERSION_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("Protocol version must use Major.Minor or Major.Minor.Patch format.")
    return f"{match.group('major')}.{match.group('minor')}"


def negotiate_protocol_version(
    *,
    header_value: str | None,
    query_value: str | None,
) -> NegotiatedProtocolVersion:
    raw_header = (header_value or "").strip()
    raw_query = (query_value or "").strip()
    explicit = bool(raw_header or raw_query)
    raw_requested = raw_header or raw_query or ADVERTISED_PROTOCOL_VERSION

    try:
        normalized_requested = normalize_protocol_version(raw_requested)
    except ValueError as exc:
        raise UnsupportedProtocolVersionError(raw_requested) from exc

    if normalized_requested != SUPPORTED_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersionError(normalized_requested)

    return NegotiatedProtocolVersion(
        protocol_version=normalized_requested,
        explicit=explicit,
    )


def set_current_protocol_version(protocol_version: str) -> Token[str | None]:
    return _CURRENT_PROTOCOL_VERSION.set(normalize_protocol_version(protocol_version))


def reset_current_protocol_version(token: Token[str | None]) -> None:
    _CURRENT_PROTOCOL_VERSION.reset(token)


def get_current_protocol_version() -> str:
    protocol_version = _CURRENT_PROTOCOL_VERSION.get()
    if protocol_version:
        return protocol_version
    return ADVERTISED_PROTOCOL_VERSION


def build_protocol_compatibility_summary() -> dict[str, Any]:
    return {
        "default_protocol_version": ADVERTISED_PROTOCOL_VERSION,
        "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "versions": {
            SUPPORTED_PROTOCOL_VERSION: {
                "enabled": True,
                "default": True,
                "status": "supported",
                "supported_features": list(V1_SUPPORTED_FEATURES),
                "known_gaps": [],
            }
        },
    }
