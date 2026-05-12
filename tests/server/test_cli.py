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
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "uv tool install --upgrade codex-a2a" in output
    assert "A2A Protocol 1.0 only." in output
    assert "codex-a2a <command> [arguments] [options]" in output
    assert "A2A_STATIC_AUTH_CREDENTIALS" not in output


def test_cli_serve_help_keeps_serve_guidance(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["serve", "--help"])

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "usage: codex-a2a serve" in output
    assert "A2A_STATIC_AUTH_CREDENTIALS" in output
    assert "Serve durable SQLite example:" in output


@pytest.mark.parametrize("version_flag", ["--version", "-v"])
def test_cli_version_does_not_require_runtime_settings(
    version_flag: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([version_flag])

    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_prints_help_when_no_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0

    output = capsys.readouterr().out
    assert "serve        Run the A2A service." in output


def test_cli_serve_command_dispatches_to_server_main() -> None:
    with mock.patch.object(app_module, "main") as serve_main:
        assert cli.main(["serve"]) == 0

    serve_main.assert_called_once_with()


def test_normalize_log_level_defaults_invalid_values_to_warning() -> None:
    assert app_module._normalize_log_level("debug") == "DEBUG"
    assert app_module._normalize_log_level("not-a-level") == "WARNING"
