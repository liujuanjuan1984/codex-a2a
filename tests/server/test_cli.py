from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import codex_a2a.cli as cli
import codex_a2a.server.application as app_module
from codex_a2a import __version__


def test_cli_help_does_not_require_runtime_settings(capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("codex_a2a.cli._serve_main") as serve_mock:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--help"])

    assert excinfo.value.code == 0
    assert "Codex A2A CLI." in capsys.readouterr().out
    serve_mock.assert_not_called()


def test_cli_version_does_not_require_runtime_settings(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock.patch("codex_a2a.cli._serve_main") as serve_mock:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--version"])

    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out
    serve_mock.assert_not_called()


def test_cli_defaults_to_serve_when_no_subcommand() -> None:
    with mock.patch("codex_a2a.cli._serve_main") as serve_mock:
        assert cli.main([]) == 0

    serve_mock.assert_called_once_with()


def test_normalize_log_level_defaults_invalid_values_to_warning() -> None:
    assert app_module._normalize_log_level("debug") == "DEBUG"
    assert app_module._normalize_log_level("not-a-level") == "WARNING"
