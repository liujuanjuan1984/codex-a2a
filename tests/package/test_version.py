from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace

from codex_a2a import _resolve_version


def test_resolve_version_prefers_package_metadata(monkeypatch) -> None:
    monkeypatch.setattr("codex_a2a.version", lambda _package: "1.2.3")

    assert _resolve_version() == "1.2.3"


def test_resolve_version_falls_back_to_scm(monkeypatch) -> None:
    def _missing_package_version(_package: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("codex_a2a.version", _missing_package_version)
    monkeypatch.setitem(
        sys.modules,
        "setuptools_scm",
        SimpleNamespace(get_version=lambda **_kwargs: "1.2.4.dev1+gabc123"),
    )

    assert _resolve_version() == "1.2.4.dev1+gabc123"


def test_resolve_version_uses_unknown_when_metadata_missing(monkeypatch) -> None:
    def _missing_package_version(_package: str) -> str:
        raise PackageNotFoundError

    def _missing_scm_version(**_kwargs: str) -> str:
        raise LookupError

    monkeypatch.setattr("codex_a2a.version", _missing_package_version)
    monkeypatch.setitem(
        sys.modules,
        "setuptools_scm",
        SimpleNamespace(get_version=_missing_scm_version),
    )

    assert _resolve_version() == "0.0.0+unknown"
