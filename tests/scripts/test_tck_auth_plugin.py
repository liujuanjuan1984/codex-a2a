import base64

import pytest
from scripts.tck_auth_plugin import _authorization_header


def test_tck_auth_plugin_builds_bearer_header(monkeypatch) -> None:
    monkeypatch.setenv("A2A_AUTH_TYPE", "bearer")
    monkeypatch.setenv("A2A_AUTH_TOKEN", "test-token")

    assert _authorization_header() == "Bearer test-token"


def test_tck_auth_plugin_builds_basic_header(monkeypatch) -> None:
    monkeypatch.setenv("A2A_AUTH_TYPE", "basic")
    monkeypatch.setenv("A2A_AUTH_USERNAME", "user")
    monkeypatch.setenv("A2A_AUTH_PASSWORD", "pass")

    encoded = base64.b64encode(b"user:pass").decode()
    assert _authorization_header() == f"Basic {encoded}"


def test_tck_auth_plugin_rejects_missing_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("A2A_AUTH_TYPE", "bearer")
    monkeypatch.delenv("A2A_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="A2A_AUTH_TOKEN"):
        _authorization_header()
