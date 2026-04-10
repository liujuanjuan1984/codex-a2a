from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_PROTOCOL_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?$")

V1_COMPATIBILITY_GAPS: tuple[str, ...] = (
    "Request-time A2A-Version negotiation is not implemented yet.",
    "JSON-RPC method aliases and transport payloads still follow the SDK-owned 0.3 baseline.",
)


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
    return (normalize_protocol_version(protocol_version),)


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
            "supported_features": [],
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
