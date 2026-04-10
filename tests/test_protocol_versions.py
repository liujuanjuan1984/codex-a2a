import pytest

from codex_a2a.protocol_versions import (
    build_protocol_compatibility_summary,
    default_supported_protocol_versions,
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


def test_protocol_compatibility_summary_declares_current_and_future_lines() -> None:
    summary = build_protocol_compatibility_summary(
        default_protocol_version="0.3.0",
        supported_protocol_versions=["0.3.0"],
    )

    assert summary["default_protocol_version"] == "0.3"
    assert summary["supported_protocol_versions"] == ["0.3"]
    assert summary["versions"]["0.3"]["enabled"] is True
    assert summary["versions"]["0.3"]["default"] is True
    assert summary["versions"]["0.3"]["status"] == "supported"
    assert summary["versions"]["1.0"]["enabled"] is False
    assert summary["versions"]["1.0"]["status"] == "future"
