from __future__ import annotations

import re
from collections.abc import Iterable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

_PROTOCOL_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?$")
_CURRENT_PROTOCOL_VERSION: ContextVar[str | None] = ContextVar(
    "_CURRENT_PROTOCOL_VERSION",
    default=None,
)

V1_COMPATIBILITY_GAPS: tuple[str, ...] = (
    (
        "Transport payloads, enums, pagination, and push-notification surfaces still "
        "follow the SDK-owned 0.3 baseline."
    ),
)


class UnsupportedProtocolVersionError(ValueError):
    def __init__(
        self,
        requested_version: str,
        *,
        supported_protocol_versions: tuple[str, ...],
        default_protocol_version: str,
    ) -> None:
        self.requested_version = requested_version
        self.supported_protocol_versions = supported_protocol_versions
        self.default_protocol_version = default_protocol_version
        supported_display = ", ".join(supported_protocol_versions)
        super().__init__(
            f"Unsupported A2A protocol version {requested_version!r}. "
            f"Supported versions: {supported_display}."
        )


@dataclass(frozen=True)
class NegotiatedProtocolVersion:
    requested_version: str
    negotiated_version: str
    explicit: bool


def normalize_protocol_version(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Protocol version must be a non-empty string.")
    match = _PROTOCOL_VERSION_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("Protocol version must use Major.Minor or Major.Minor.Patch format.")
    return f"{match.group('major')}.{match.group('minor')}"


def normalize_protocol_versions(values: Iterable[str]) -> tuple[str, ...]:
    normalized_versions: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_protocol_version(str(value))
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_versions.append(normalized)
    if not normalized_versions:
        raise ValueError("At least one supported protocol version must be declared.")
    return tuple(normalized_versions)


def default_supported_protocol_versions(protocol_version: str) -> tuple[str, ...]:
    normalized = normalize_protocol_version(protocol_version)
    if normalized == "0.3":
        return ("0.3", "1.0")
    return (normalized,)


def negotiate_protocol_version(
    *,
    header_value: str | None,
    query_value: str | None,
    default_protocol_version: str,
    supported_protocol_versions: Iterable[str],
) -> NegotiatedProtocolVersion:
    normalized_default = normalize_protocol_version(default_protocol_version)
    normalized_supported = normalize_protocol_versions(supported_protocol_versions)

    raw_header = (header_value or "").strip()
    raw_query = (query_value or "").strip()
    explicit = bool(raw_header or raw_query)
    raw_requested = raw_header or raw_query or normalized_default

    try:
        normalized_requested = normalize_protocol_version(raw_requested)
    except ValueError as exc:
        raise UnsupportedProtocolVersionError(
            raw_requested,
            supported_protocol_versions=normalized_supported,
            default_protocol_version=normalized_default,
        ) from exc

    if normalized_requested not in normalized_supported:
        raise UnsupportedProtocolVersionError(
            normalized_requested,
            supported_protocol_versions=normalized_supported,
            default_protocol_version=normalized_default,
        )

    return NegotiatedProtocolVersion(
        requested_version=normalized_requested,
        negotiated_version=normalized_requested,
        explicit=explicit,
    )


def set_current_protocol_version(protocol_version: str) -> Token[str | None]:
    return _CURRENT_PROTOCOL_VERSION.set(normalize_protocol_version(protocol_version))


def reset_current_protocol_version(token: Token[str | None]) -> None:
    _CURRENT_PROTOCOL_VERSION.reset(token)


def get_current_protocol_version(default: str) -> str:
    protocol_version = _CURRENT_PROTOCOL_VERSION.get()
    if protocol_version:
        return protocol_version
    return normalize_protocol_version(default)


def build_protocol_compatibility_summary(
    *,
    default_protocol_version: str,
    supported_protocol_versions: Iterable[str],
) -> dict[str, Any]:
    normalized_default = normalize_protocol_version(default_protocol_version)
    normalized_supported = normalize_protocol_versions(supported_protocol_versions)
    versions: dict[str, dict[str, Any]] = {
        "0.3": {
            "enabled": "0.3" in normalized_supported,
            "default": normalized_default == "0.3",
            "status": "supported",
            "supported_features": [
                "Default compatibility line for the current SDK baseline.",
                "SDK-owned JSON-RPC and HTTP+JSON method surface.",
                "SDK-owned transport payloads, enums, pagination, and push-notification surfaces.",
            ],
            "known_gaps": [],
        },
        "1.0": {
            "enabled": "1.0" in normalized_supported,
            "default": normalized_default == "1.0",
            "status": "future" if "1.0" not in normalized_supported else "partial",
            "supported_features": (
                [
                    "A2A-Version request-time negotiation and response header echo.",
                    "PascalCase JSON-RPC method aliases for the current SDK-backed method surface.",
                    "Protocol-aware JSON-RPC and HTTP error shaping.",
                ]
                if "1.0" in normalized_supported
                else []
            ),
            "known_gaps": list(V1_COMPATIBILITY_GAPS),
        },
    }

    for version in normalized_supported:
        if version in versions:
            continue
        versions[version] = {
            "enabled": True,
            "default": normalized_default == version,
            "status": "custom",
            "supported_features": [
                "Declared by repository configuration.",
                "Version-specific compatibility details are not yet modeled.",
            ],
            "known_gaps": [
                "This protocol line does not yet have a dedicated compatibility summary.",
            ],
        }

    return {
        "default_protocol_version": normalized_default,
        "supported_protocol_versions": list(normalized_supported),
        "versions": versions,
    }
