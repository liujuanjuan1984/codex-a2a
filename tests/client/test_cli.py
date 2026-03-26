from __future__ import annotations

from codex_a2a.cli import build_parser, main


def test_call_parser_no_longer_accepts_token_flag() -> None:
    parser = build_parser()

    namespace = parser.parse_args(["call", "https://peer.example.com", "hello"])

    assert namespace.command == "call"
    assert not hasattr(namespace, "token")


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
