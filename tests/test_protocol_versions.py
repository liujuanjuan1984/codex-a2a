import pytest

from codex_a2a.protocol_versions import (
    UnsupportedProtocolVersionError,
    build_protocol_compatibility_summary,
    default_supported_protocol_versions,
    negotiate_protocol_version,
    normalize_protocol_version,
    normalize_protocol_versions,
)


def test_normalize_protocol_version_accepts_major_minor_patch() -> None:
    assert normalize_protocol_version("0.3.0") == "0.3"
    assert normalize_protocol_version(" 1.0 ") == "1.0"


def test_normalize_protocol_versions_deduplicates_in_order() -> None:
    assert normalize_protocol_versions(["0.3.0", "0.3", "1.0.0"]) == ("0.3", "1.0")


def test_normalize_protocol_version_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Major.Minor"):
        normalize_protocol_version("v0.3")


def test_default_supported_protocol_versions_uses_declared_line() -> None:
    assert default_supported_protocol_versions("0.3.0") == ("0.3",)
    assert default_supported_protocol_versions("1.0.0") == ("1.0",)


def test_protocol_compatibility_summary_declares_supported_lines_only() -> None:
    summary = build_protocol_compatibility_summary(
        default_protocol_version="1.0.0",
        supported_protocol_versions=["1.0"],
    )

    assert summary["default_protocol_version"] == "1.0"
    assert summary["supported_protocol_versions"] == ["1.0"]
    assert set(summary["versions"]) == {"1.0"}
    assert summary["versions"]["1.0"]["enabled"] is True
    assert summary["versions"]["1.0"]["default"] is True
    assert summary["versions"]["1.0"]["status"] == "supported"
    assert "A2A-Version" in summary["versions"]["1.0"]["supported_features"][0]
    assert summary["versions"]["1.0"]["known_gaps"] == []


def test_negotiate_protocol_version_defaults_to_configured_baseline() -> None:
    negotiated = negotiate_protocol_version(
        header_value=None,
        query_value=None,
        default_protocol_version="1.0.0",
        supported_protocol_versions=["1.0"],
    )

    assert negotiated.requested_version == "1.0"
    assert negotiated.negotiated_version == "1.0"
    assert negotiated.explicit is False


def test_negotiate_protocol_version_prefers_header_over_query() -> None:
    negotiated = negotiate_protocol_version(
        header_value="1.0",
        query_value="1.0",
        default_protocol_version="1.0.0",
        supported_protocol_versions=["1.0"],
    )

    assert negotiated.requested_version == "1.0"
    assert negotiated.negotiated_version == "1.0"
    assert negotiated.explicit is True


def test_negotiate_protocol_version_rejects_unsupported_line() -> None:
    with pytest.raises(UnsupportedProtocolVersionError) as exc_info:
        negotiate_protocol_version(
            header_value="2.0",
            query_value=None,
            default_protocol_version="1.0.0",
            supported_protocol_versions=["1.0"],
        )

    assert exc_info.value.requested_version == "2.0"
    assert exc_info.value.supported_protocol_versions == ("1.0",)
