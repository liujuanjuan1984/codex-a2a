import httpx
import pytest

from codex_a2a_server.app import SESSION_QUERY_EXTENSION_URI, build_agent_card, create_app
from codex_a2a_server.extension_contracts import build_session_query_extension_params
from tests.helpers import DummySessionQueryCodexClient as DummyCodexClient
from tests.helpers import make_settings


def test_session_query_extension_ssot_matches_agent_card_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    card = build_agent_card(settings)
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}

    session_query = ext_by_uri[SESSION_QUERY_EXTENSION_URI]
    deployment_context = session_query.params["deployment_context"]
    expected = build_session_query_extension_params(
        deployment_context=deployment_context,
        session_shell_enabled=settings.a2a_enable_session_shell,
    )

    assert session_query.params == expected, (
        "Session query extension drifted from extension_contracts SSOT."
    )


def test_session_query_extension_ssot_matches_agent_card_contract_when_shell_disabled() -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_enable_session_shell=False,
    )
    card = build_agent_card(settings)
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}

    session_query = ext_by_uri[SESSION_QUERY_EXTENSION_URI]
    deployment_context = session_query.params["deployment_context"]
    expected = build_session_query_extension_params(
        deployment_context=deployment_context,
        session_shell_enabled=settings.a2a_enable_session_shell,
    )

    assert session_query.params == expected, (
        "Disabled shell session query contract drifted from extension_contracts SSOT."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("codex.sessions.list", {"limit": 10}),
        ("codex.sessions.messages.list", {"session_id": "s-1", "limit": 5}),
        (
            "codex.sessions.prompt_async",
            {
                "session_id": "s-1",
                "request": {"parts": [{"type": "text", "text": "Continue"}]},
            },
        ),
        (
            "codex.sessions.command",
            {
                "session_id": "s-1",
                "request": {"command": "plan", "arguments": "show current work"},
            },
        ),
        (
            "codex.sessions.shell",
            {
                "session_id": "s-1",
                "request": {"command": "pwd"},
            },
        ),
    ],
)
async def test_session_query_runtime_result_envelope_matches_declared_contract(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    params: dict[str, object],
) -> None:
    import codex_a2a_server.app as app_module

    settings = make_settings(a2a_bearer_token="t-1", a2a_log_payloads=False, codex_timeout=1.0)
    card = build_agent_card(settings)
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    envelope_by_method = ext_by_uri[SESSION_QUERY_EXTENSION_URI].params["result_envelope"][
        "by_method"
    ]
    expected_envelope = envelope_by_method[method]

    dummy = DummyCodexClient(settings)
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings: dummy)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer t-1"},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )

    assert response.status_code == 200
    payload = response.json()
    assert sorted(payload["result"].keys()) == sorted(expected_envelope["fields"])

    items_field = expected_envelope.get("items_field")
    if items_field is not None:
        assert isinstance(payload["result"][items_field], list)
