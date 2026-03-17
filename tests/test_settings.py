import os
from unittest import mock

import pytest
from pydantic import ValidationError

from codex_a2a_server.app import _warn_on_non_recommended_stream_heartbeat
from codex_a2a_server.config import Settings


def test_settings_missing_required():
    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()
        # Should mention missing required fields
        errors = excinfo.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "A2A_BEARER_TOKEN" in field_names


def test_settings_valid():
    env = {
        "A2A_BEARER_TOKEN": "test-token",
        "CODEX_TIMEOUT": "300",
        "CODEX_MODEL_REASONING_EFFORT": "high",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
        assert settings.a2a_bearer_token == "test-token"
        assert settings.codex_timeout == 300.0
        assert settings.codex_model_reasoning_effort == "high"


def test_parse_oauth_scopes():
    env = {
        "A2A_BEARER_TOKEN": "test",
        "A2A_OAUTH_SCOPES": "scope1, scope2,,scope3 ",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
        assert settings.a2a_oauth_scopes == {"scope1": "", "scope2": "", "scope3": ""}


def test_stream_heartbeat_rejects_values_below_minimum():
    env = {
        "A2A_BEARER_TOKEN": "test-token",
        "A2A_STREAM_HEARTBEAT_SECONDS": "4",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()
    assert "at least 5 seconds" in str(excinfo.value)


def test_stream_heartbeat_rejects_values_above_maximum():
    env = {
        "A2A_BEARER_TOKEN": "test-token",
        "A2A_STREAM_HEARTBEAT_SECONDS": "61",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValidationError) as excinfo:
            Settings.from_env()
    assert "at most 60 seconds" in str(excinfo.value)


def test_stream_heartbeat_accepts_recommended_value_without_warning(caplog):
    settings = Settings(
        a2a_bearer_token="test-token",
        a2a_stream_heartbeat_seconds=12,
    )

    with caplog.at_level("WARNING", logger="codex_a2a_server.app"):
        _warn_on_non_recommended_stream_heartbeat(settings)

    assert caplog.records == []


def test_stream_heartbeat_warns_when_value_is_outside_recommended_range(caplog):
    settings = Settings(
        a2a_bearer_token="test-token",
        a2a_stream_heartbeat_seconds=20,
    )

    with caplog.at_level("WARNING", logger="codex_a2a_server.app"):
        _warn_on_non_recommended_stream_heartbeat(settings)

    assert any(
        "outside the recommended range 10-15 seconds" in record.message for record in caplog.records
    )
