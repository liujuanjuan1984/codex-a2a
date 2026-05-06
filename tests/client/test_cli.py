from __future__ import annotations

from codex_a2a.cli import CLI_REPOSITORY_URL, build_parser, main


def test_call_parser_no_longer_accepts_token_flag() -> None:
    parser = build_parser()

    namespace = parser.parse_args(["call", "https://peer.example.com", "hello"])

    assert namespace.command == "call"
    assert not hasattr(namespace, "token")


def test_root_help_includes_branding_and_compact_commands_section() -> None:
    help_text = build_parser().format_help()

    assert f"repo: {CLI_REPOSITORY_URL}" in help_text
    assert "uv tool install --upgrade codex-a2a" in help_text
    assert "A2A Protocol 1.0 by default, with core 0.3 compatibility." in help_text
    assert "codex-a2a <command> [arguments] [options]" in help_text
    assert "commands:\n    serve        Run the A2A service." in help_text
    assert "commands:\n  command" not in help_text
    assert "Codex runtime quick start:" in help_text
    assert "codex --version" in help_text
    assert "codex app-server --help" in help_text
    assert "Codex note:" in help_text
    assert "Serve required environment:" in help_text
    assert "A2A_STATIC_AUTH_CREDENTIALS" in help_text
    assert "Serve common environment:" in help_text
    assert "A2A_DATABASE_URL" in help_text
    assert "CODEX_WORKSPACE_ROOT" in help_text
    assert "Serve minimal example:" in help_text
    assert "Serve durable SQLite example:" in help_text
    assert "codex-a2a serve" in help_text
    assert "Call examples:" in help_text
    assert 'codex-a2a call http://other-agent:8000/.well-known/agent-card.json "How are you?"' in (
        help_text
    )
    assert 'A2A_CLIENT_BASIC_AUTH="user:pass"' in help_text
    assert "Call note:" in help_text
    assert "card URLs are the preferred example form." in help_text
    assert "usage:" not in help_text


def test_call_help_stays_compact() -> None:
    parser = build_parser()
    call_parser = parser._subparsers._group_actions[0].choices["call"]

    help_text = call_parser.format_help()

    assert "usage: codex-a2a call" in help_text
    assert "Example:" not in help_text
    assert "Authenticated example:" not in help_text


def test_call_command_reads_bearer_token_from_environment(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_run_call(
        agent_url: str,
        text: str,
        bearer_token: str | None = None,
        basic_auth: str | None = None,
    ) -> int:
        captured["agent_url"] = agent_url
        captured["text"] = text
        captured["bearer_token"] = bearer_token
        captured["basic_auth"] = basic_auth
        return 0

    monkeypatch.setattr("codex_a2a.cli.run_call", _fake_run_call)
    monkeypatch.setenv("A2A_CLIENT_BEARER_TOKEN", "peer-token")
    monkeypatch.delenv("A2A_CLIENT_BASIC_AUTH", raising=False)

    exit_code = main(["call", "https://peer.example.com", "hello"])

    assert exit_code == 0
    assert captured == {
        "agent_url": "https://peer.example.com",
        "text": "hello",
        "bearer_token": "peer-token",
        "basic_auth": None,
    }


def test_call_command_reads_basic_auth_from_environment(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_run_call(
        agent_url: str,
        text: str,
        bearer_token: str | None = None,
        basic_auth: str | None = None,
    ) -> int:
        captured["agent_url"] = agent_url
        captured["text"] = text
        captured["bearer_token"] = bearer_token
        captured["basic_auth"] = basic_auth
        return 0

    monkeypatch.setattr("codex_a2a.cli.run_call", _fake_run_call)
    monkeypatch.delenv("A2A_CLIENT_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("A2A_CLIENT_BASIC_AUTH", "user:pass")

    exit_code = main(["call", "https://peer.example.com", "hello"])

    assert exit_code == 0
    assert captured == {
        "agent_url": "https://peer.example.com",
        "text": "hello",
        "bearer_token": None,
        "basic_auth": "user:pass",
    }


def test_call_command_prefers_bearer_token_when_both_env_vars_are_present(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_run_call(
        agent_url: str,
        text: str,
        bearer_token: str | None = None,
        basic_auth: str | None = None,
    ) -> int:
        captured["agent_url"] = agent_url
        captured["text"] = text
        captured["bearer_token"] = bearer_token
        captured["basic_auth"] = basic_auth
        return 0

    monkeypatch.setattr("codex_a2a.cli.run_call", _fake_run_call)
    monkeypatch.setenv("A2A_CLIENT_BEARER_TOKEN", "peer-token")
    monkeypatch.setenv("A2A_CLIENT_BASIC_AUTH", "user:pass")

    exit_code = main(["call", "https://peer.example.com", "hello"])

    assert exit_code == 0
    assert captured == {
        "agent_url": "https://peer.example.com",
        "text": "hello",
        "bearer_token": "peer-token",
        "basic_auth": "user:pass",
    }
