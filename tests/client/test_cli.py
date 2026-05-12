from __future__ import annotations

import pytest

from codex_a2a.cli import CLI_REPOSITORY_URL, build_parser, main, run_call


def test_call_parser_no_longer_accepts_token_flag() -> None:
    parser = build_parser()

    namespace = parser.parse_args(["call", "https://peer.example.com", "hello"])

    assert namespace.command == "call"
    assert not hasattr(namespace, "token")


def test_root_help_includes_branding_and_compact_commands_section() -> None:
    help_text = build_parser().format_help()

    assert f"repo: {CLI_REPOSITORY_URL}" in help_text
    assert "uv tool install --upgrade codex-a2a" in help_text
    assert "A2A Protocol 1.0 only." in help_text
    assert "codex-a2a <command> [arguments] [options]" in help_text
    assert "commands:\n    serve        Run the A2A service." in help_text
    assert "commands:\n  command" not in help_text
    assert "Codex runtime quick start:" in help_text
    assert "codex --version" in help_text
    assert "codex app-server --help" in help_text
    assert "Codex note:" in help_text
    assert "Call examples:" in help_text
    assert 'codex-a2a call http://other-agent:8000/.well-known/agent-card.json "How are you?"' in (
        help_text
    )
    assert 'A2A_CLIENT_BASIC_AUTH="user:pass"' in help_text
    assert "Call note:" in help_text
    assert "card URLs are the preferred example form." in help_text
    assert "Serve required environment:" not in help_text
    assert "A2A_STATIC_AUTH_CREDENTIALS" not in help_text
    assert "Serve common environment:" not in help_text
    assert "A2A_DATABASE_URL" not in help_text
    assert "CODEX_WORKSPACE_ROOT=/abs/path/to/workspace \\\n  codex-a2a serve" not in help_text
    assert "usage:" not in help_text


def test_call_help_stays_compact() -> None:
    parser = build_parser()
    call_parser = parser._subparsers._group_actions[0].choices["call"]

    help_text = call_parser.format_help()

    assert "usage: codex-a2a call" in help_text
    assert "Example:" not in help_text
    assert "Authenticated example:" not in help_text


def test_serve_help_contains_serve_specific_guidance() -> None:
    parser = build_parser()
    serve_parser = parser._subparsers._group_actions[0].choices["serve"]

    help_text = serve_parser.format_help()

    assert "usage: codex-a2a serve" in help_text
    assert "Run the Codex A2A service." in help_text
    assert "Serve required environment:" in help_text
    assert "A2A_STATIC_AUTH_CREDENTIALS" in help_text
    assert "Serve common environment:" in help_text
    assert "A2A_DATABASE_URL" in help_text
    assert "CODEX_WORKSPACE_ROOT" in help_text
    assert "Serve minimal example:" in help_text
    assert "Serve durable SQLite example:" in help_text


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


@pytest.mark.asyncio
async def test_run_call_streams_text_without_fallback(monkeypatch, capsys) -> None:
    clients: list[object] = []

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            self.config = config
            self.closed = False
            self.send_called = False
            self.send_message_calls: list[dict[str, object]] = []
            clients.append(self)

        async def send_message(self, text: str, *, metadata=None, accepted_output_modes=None):
            self.send_message_calls.append(
                {
                    "text": text,
                    "metadata": metadata,
                    "accepted_output_modes": accepted_output_modes,
                }
            )
            for chunk in ({"text": "Hel"}, {"text": "lo"}):
                yield chunk

        async def send(self, request):  # noqa: ANN001
            self.send_called = True
            return {"text": "fallback"}

        async def close(self) -> None:
            self.closed = True

        @staticmethod
        def extract_text(response):  # noqa: ANN001
            return response.get("text")

    monkeypatch.setattr("codex_a2a.cli.A2AClient", FakeClient)

    exit_code = await run_call(
        "https://peer.example.com/.well-known/agent-card.json",
        "hello",
        bearer_token="peer-token",
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "Hello\n"
    client = clients[0]
    assert client.config.agent_url == "https://peer.example.com/.well-known/agent-card.json"
    assert client.config.default_headers["Authorization"] == "Bearer peer-token"
    assert client.send_message_calls == [
        {
            "text": "hello",
            "metadata": {"authorization": "Bearer peer-token"},
            "accepted_output_modes": ["text/plain"],
        }
    ]
    assert client.send_called is False
    assert client.closed is True


@pytest.mark.asyncio
async def test_run_call_falls_back_to_send_when_stream_has_no_text(monkeypatch, capsys) -> None:
    clients: list[object] = []

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            self.config = config
            self.closed = False
            self.send_requests: list[object] = []
            clients.append(self)

        async def send_message(self, text: str, *, metadata=None, accepted_output_modes=None):
            del text, metadata, accepted_output_modes
            for chunk in ({}, {"text": ""}):
                yield chunk

        async def send(self, request):  # noqa: ANN001
            self.send_requests.append(request)
            return {"text": "fallback"}

        async def close(self) -> None:
            self.closed = True

        @staticmethod
        def extract_text(response):  # noqa: ANN001
            return response.get("text")

    monkeypatch.setattr("codex_a2a.cli.A2AClient", FakeClient)

    exit_code = await run_call(
        "https://peer.example.com/.well-known/agent-card.json",
        "hello",
        basic_auth="user:pass",
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "fallback\n"
    client = clients[0]
    assert len(client.send_requests) == 1
    assert client.send_requests[0].metadata == {"authorization": "Basic dXNlcjpwYXNz"}
    assert client.closed is True


@pytest.mark.asyncio
async def test_run_call_reports_errors_and_still_closes_client(monkeypatch, capsys) -> None:
    clients: list[object] = []

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            del config
            self.closed = False
            clients.append(self)

        async def send_message(self, text: str, *, metadata=None, accepted_output_modes=None):
            del text, metadata, accepted_output_modes
            raise RuntimeError("boom")
            yield {}

        async def close(self) -> None:
            self.closed = True

        @staticmethod
        def extract_text(response):  # noqa: ANN001
            return response.get("text")

    monkeypatch.setattr("codex_a2a.cli.A2AClient", FakeClient)

    exit_code = await run_call("https://peer.example.com/.well-known/agent-card.json", "hello")

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "[Error] boom" in stderr
    assert clients[0].closed is True
