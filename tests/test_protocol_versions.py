import pytest

from codex_a2a.protocol_versions import (
    UnsupportedProtocolVersionError,
    build_protocol_compatibility_summary,
    negotiate_protocol_version,
    normalize_protocol_version,
)


def test_normalize_protocol_version_accepts_major_minor_patch() -> None:
    assert normalize_protocol_version("2.0.0") == "2.0"
    assert normalize_protocol_version(" 1.0 ") == "1.0"


def test_normalize_protocol_version_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Major.Minor"):
        normalize_protocol_version("v1.0")


def test_protocol_compatibility_summary_declares_supported_lines_only() -> None:
    summary = build_protocol_compatibility_summary()

    assert summary["default_protocol_version"] == "1.0"
    assert summary["supported_protocol_versions"] == ["1.0", "0.3"]
    assert set(summary["versions"]) == {"1.0", "0.3"}
    assert summary["versions"]["1.0"]["enabled"] is True
    assert summary["versions"]["1.0"]["default"] is True
    assert summary["versions"]["1.0"]["status"] == "supported"
    assert "A2A-Version" in summary["versions"]["1.0"]["supported_features"][0]
    assert summary["versions"]["1.0"]["known_gaps"] == []
    assert summary["versions"]["0.3"]["enabled"] is True
    assert summary["versions"]["0.3"]["default"] is False
    assert "SDK-managed A2A 0.3" in summary["versions"]["0.3"]["supported_features"][1]
    assert "codex.*" in summary["versions"]["0.3"]["known_gaps"][0]


def test_protocol_compatibility_summary_can_reorder_default_line() -> None:
    summary = build_protocol_compatibility_summary(default_protocol_version="0.3")

    assert summary["default_protocol_version"] == "0.3"
    assert summary["supported_protocol_versions"] == ["0.3", "1.0"]
    assert summary["versions"]["0.3"]["default"] is True
    assert summary["versions"]["1.0"]["default"] is False


def test_negotiate_protocol_version_defaults_to_configured_baseline() -> None:
    negotiated = negotiate_protocol_version(
        header_value=None,
        query_value=None,
    )

    assert negotiated.protocol_version == "1.0"
    assert negotiated.explicit is False


def test_negotiate_protocol_version_prefers_header_over_query() -> None:
    negotiated = negotiate_protocol_version(
        header_value="1.0",
        query_value="1.0",
    )

    assert negotiated.protocol_version == "1.0"
    assert negotiated.explicit is True


def test_negotiate_protocol_version_accepts_0_3_when_explicit() -> None:
    negotiated = negotiate_protocol_version(
        header_value="0.3.0",
        query_value=None,
    )

    assert negotiated.protocol_version == "0.3"
    assert negotiated.explicit is True


def test_negotiate_protocol_version_rejects_unsupported_line() -> None:
    with pytest.raises(UnsupportedProtocolVersionError) as exc_info:
        negotiate_protocol_version(
            header_value="2.0",
            query_value=None,
        )

    assert exc_info.value.requested_version == "2.0"
    assert exc_info.value.supported_protocol_versions == ("1.0", "0.3")
