from pathlib import Path

import httpx
import pytest

from codex_a2a.contracts.extensions import (
    CORE_JSONRPC_PATH,
    EXTENSION_JSONRPC_PATH,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_DEFAULT_LIMIT,
    STREAMING_EXTENSION_URI,
    build_capability_snapshot,
    build_compatibility_profile_params,
    build_discovery_extension_params,
    build_exec_control_extension_params,
    build_interrupt_callback_extension_params,
    build_interrupt_recovery_extension_params,
    build_review_control_extension_params,
    build_session_binding_extension_params,
    build_session_query_extension_params,
    build_streaming_extension_params,
    build_thread_lifecycle_extension_params,
    build_turn_control_extension_params,
    build_wire_contract_extension_params,
)
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import build_authenticated_extended_agent_card
from codex_a2a.server.application import create_app
from codex_a2a.server.openapi_contract_fragments import (
    build_openapi_codex_contracts,
)
from tests.support.dummy_clients import DummySessionQueryCodexClient as DummyCodexClient
from tests.support.settings import make_settings


def _extract_heading_section(markdown: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = markdown.find(marker)
    if start < 0:
        raise AssertionError(f"Missing heading {heading!r} in docs/guide.md.")

    start += len(marker)
    end = markdown.find("\n## ", start)
    if end < 0:
        end = len(markdown)
    return markdown[start:end]


def _example_params_include_field(payload: object, dotted_field: str) -> bool:
    current = payload
    for segment in dotted_field.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return True


def _codex_contracts(settings) -> dict[str, dict[str, object]]:  # noqa: ANN001
    runtime_profile = build_runtime_profile(settings)
    return build_openapi_codex_contracts(
        settings=settings,
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )


def test_capability_snapshot_tracks_session_query_only_surface() -> None:
    runtime_profile = build_runtime_profile(make_settings(a2a_bearer_token="test-token"))

    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)

    assert snapshot.session_query_method_keys == (
        "list_sessions",
        "get_session_messages",
    )
    assert "codex.sessions.command" not in snapshot.supported_jsonrpc_methods
    assert "codex.sessions.prompt_async" not in snapshot.supported_jsonrpc_methods


def test_session_query_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_session_query_extension_params(
        runtime_profile=runtime_profile,
    )
    session_query = _codex_contracts(settings)["session_query"]

    assert session_query == expected, (
        "Session query extension drifted from extension_contracts SSOT."
    )
    assert session_query["pagination"]["default_limit"] == SESSION_QUERY_DEFAULT_LIMIT
    assert session_query["pagination"]["behavior"] == "mixed"


def test_discovery_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_discovery_extension_params(runtime_profile=runtime_profile)
    discovery = _codex_contracts(settings)["discovery"]

    assert discovery == expected, "Discovery extension drifted from extension_contracts SSOT."


def test_thread_lifecycle_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_thread_lifecycle_extension_params(runtime_profile=runtime_profile)
    thread_lifecycle = _codex_contracts(settings)["thread_lifecycle"]

    assert thread_lifecycle == expected, (
        "Thread lifecycle extension drifted from extension_contracts SSOT."
    )


def test_interrupt_recovery_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_interrupt_recovery_extension_params(runtime_profile=runtime_profile)
    interrupt_recovery = _codex_contracts(settings)["interrupt_recovery"]

    assert interrupt_recovery == expected, (
        "Interrupt recovery extension drifted from extension_contracts SSOT."
    )


def test_turn_control_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_turn_control_extension_params(runtime_profile=runtime_profile)
    turn_control = _codex_contracts(settings)["turn_control"]

    assert turn_control == expected, "Turn control extension drifted from extension_contracts SSOT."


def test_review_control_contract_ssot_matches_openapi_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    expected = build_review_control_extension_params(runtime_profile=runtime_profile)
    review_control = _codex_contracts(settings)["review_control"]

    assert review_control == expected, (
        "Review control extension drifted from extension_contracts SSOT."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("codex.sessions.list", {"limit": 10}),
        ("codex.sessions.messages.list", {"session_id": "s-1", "limit": 5}),
    ],
)
async def test_session_query_runtime_result_envelope_matches_declared_contract(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    params: dict[str, object],
) -> None:
    import codex_a2a.server.application as app_module

    settings = make_settings(
        a2a_bearer_token="t-1",
        a2a_basic_auth_username="operator",
        a2a_basic_auth_password="op-pass",  # pragma: allowlist secret
        a2a_log_payloads=False,
        codex_timeout=1.0,
    )
    method_contracts = _codex_contracts(settings)["session_query"]["method_contracts"]
    expected_result = method_contracts[method]["result"]

    dummy = DummyCodexClient(settings)
    monkeypatch.setattr(app_module, "CodexClient", lambda _settings, **kwargs: dummy)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            EXTENSION_JSONRPC_PATH,
            headers={"Authorization": "Bearer t-1"},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )

    assert response.status_code == 200
    payload = response.json()
    assert sorted(payload["result"].keys()) == sorted(expected_result["fields"])

    items_field = expected_result.get("items_field")
    if items_field is not None:
        assert isinstance(payload["result"][items_field], list)


def test_session_query_result_envelope_omits_method_level_contracts() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    session_query = _codex_contracts(settings)["session_query"]

    assert session_query["result_envelope"] == {}


def test_openapi_jsonrpc_contract_extension_matches_ssot() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)
    app = create_app(settings)
    openapi = app.openapi()
    core_contract = openapi["paths"][CORE_JSONRPC_PATH]["post"].get("x-a2a-extension-contracts")
    assert isinstance(core_contract, dict), (
        "POST / OpenAPI is missing x-a2a-extension-contracts metadata."
    )
    codex_contract = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"].get("x-codex-contracts")
    assert isinstance(codex_contract, dict), (
        f"POST {EXTENSION_JSONRPC_PATH} OpenAPI is missing x-codex-contracts metadata."
    )

    session_binding = core_contract["session_binding"]
    streaming = core_contract["streaming"]
    session_query = codex_contract["session_query"]
    discovery = codex_contract["discovery"]
    interrupt_recovery = codex_contract["interrupt_recovery"]
    interrupt_callback = codex_contract["interrupt_callback"]
    exec_control = codex_contract["exec_control"]
    thread_lifecycle = codex_contract["thread_lifecycle"]
    turn_control = codex_contract["turn_control"]
    review_control = codex_contract["review_control"]
    wire_contract = codex_contract["wire_contract"]
    compatibility_profile = codex_contract["compatibility_profile"]
    expected_session_binding = build_session_binding_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_streaming = build_streaming_extension_params()
    expected_session_query = build_session_query_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_discovery = build_discovery_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_interrupt_recovery = build_interrupt_recovery_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_interrupt_callback = build_interrupt_callback_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_exec_control = build_exec_control_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_thread_lifecycle = build_thread_lifecycle_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_turn_control = build_turn_control_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_review_control = build_review_control_extension_params(
        runtime_profile=runtime_profile,
    )
    expected_wire_contract = build_wire_contract_extension_params(
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )
    expected_compatibility_profile = build_compatibility_profile_params(
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )

    assert session_binding == expected_session_binding, (
        "OpenAPI session binding contract drifted from extension_contracts SSOT."
    )
    assert streaming == expected_streaming, (
        "OpenAPI streaming contract drifted from extension_contracts SSOT."
    )
    assert session_query == expected_session_query, (
        "OpenAPI session query contract drifted from extension_contracts SSOT."
    )
    assert discovery == expected_discovery, (
        "OpenAPI discovery contract drifted from extension_contracts SSOT."
    )
    assert interrupt_recovery == expected_interrupt_recovery, (
        "OpenAPI interrupt recovery contract drifted from extension_contracts SSOT."
    )
    assert interrupt_callback == expected_interrupt_callback, (
        "OpenAPI interrupt callback contract drifted from extension_contracts SSOT."
    )
    assert exec_control == expected_exec_control, (
        "OpenAPI exec control contract drifted from extension_contracts SSOT."
    )
    assert thread_lifecycle == expected_thread_lifecycle, (
        "OpenAPI thread lifecycle contract drifted from extension_contracts SSOT."
    )
    assert turn_control == expected_turn_control, (
        "OpenAPI turn control contract drifted from extension_contracts SSOT."
    )
    assert review_control == expected_review_control, (
        "OpenAPI review control contract drifted from extension_contracts SSOT."
    )
    assert wire_contract == expected_wire_contract, (
        "OpenAPI wire contract drifted from extension_contracts SSOT."
    )
    assert compatibility_profile == expected_compatibility_profile, (
        "OpenAPI compatibility profile drifted from extension_contracts SSOT."
    )
    assert (
        compatibility_profile["protocol_compatibility"] == wire_contract["protocol_compatibility"]
    ), "OpenAPI protocol compatibility summary drifted between profile and wire contract."


def test_openapi_and_agent_card_contract_partitions_match() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    card = build_authenticated_extended_agent_card(settings)
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    openapi = create_app(settings).openapi()
    core_contract = openapi["paths"][CORE_JSONRPC_PATH]["post"]["x-a2a-extension-contracts"]
    core_codex_contract = openapi["paths"][CORE_JSONRPC_PATH]["post"]["x-codex-contracts"]
    extension_codex_contract = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]["x-codex-contracts"]

    assert core_contract["session_binding"] == ext_by_uri[SESSION_BINDING_EXTENSION_URI].params
    assert core_contract["streaming"] == ext_by_uri[STREAMING_EXTENSION_URI].params
    assert set(ext_by_uri) == {SESSION_BINDING_EXTENSION_URI, STREAMING_EXTENSION_URI}
    assert core_codex_contract["wire_contract"] == extension_codex_contract["wire_contract"]
    assert (
        core_codex_contract["compatibility_profile"]
        == extension_codex_contract["compatibility_profile"]
    )


def test_guide_mentions_declared_streaming_contract_fields() -> None:
    guide_text = Path("docs/guide.md").read_text()
    streaming_contract = build_streaming_extension_params()

    required_doc_fragments = [
        streaming_contract["artifact_metadata_field"],
        streaming_contract["session_metadata_field"],
        streaming_contract["session_fields"]["title"],
        streaming_contract["interrupt_fields"]["phase"],
        streaming_contract["interrupt_fields"]["resolution"],
        streaming_contract["usage_fields"]["reasoning_tokens"],
        streaming_contract["usage_fields"]["cache_read_tokens"],
        streaming_contract["usage_fields"]["raw"],
        "tool_call_payload_contract",
    ]

    for fragment in required_doc_fragments:
        assert fragment in guide_text, (
            f"docs/guide.md is missing streaming contract fragment {fragment!r}."
        )


def test_guide_mentions_resubscribe_service_level_behavior() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()
    wire_contract = build_wire_contract_extension_params(
        protocol_version="1.0.0",
        runtime_profile=build_runtime_profile(make_settings(a2a_bearer_token="test-token")),
        supported_protocol_versions=["1.0"],
        default_protocol_version="1.0",
    )
    assert "SubscribeToTask" in wire_contract["service_behaviors"]

    assert "replay-once" in guide_text
    assert "one final task snapshot" in guide_text
    assert "service-level" in guide_text
    assert "terminal `SubscribeToTask` replay-once behavior" in compatibility_text


def test_guide_mentions_declared_rich_input_contract() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()
    rich_input = build_session_query_extension_params(
        runtime_profile=build_runtime_profile(make_settings(a2a_bearer_token="test-token")),
    )["rich_input"]

    assert "core A2A `SendMessage` and `SendStreamingMessage`" in guide_text
    assert 'Part(data={"type":"mention"|"skill", ...})' in guide_text
    assert "turn/start.input[].type=input_image" in guide_text
    assert "local_image" in guide_text

    for fragment in rich_input["supported_part_types"]:
        assert fragment in guide_text

    assert "Rich input mapping is compatibility-sensitive" in compatibility_text


def test_guide_mentions_declared_discovery_contract() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()
    discovery_contract = build_discovery_extension_params(
        runtime_profile=build_runtime_profile(make_settings(a2a_bearer_token="test-token")),
    )

    assert "codex.discovery.skills.list" in guide_text
    assert "codex.discovery.apps.list" in guide_text
    assert "codex.discovery.plugins.list" in guide_text
    assert "codex.discovery.plugins.read" in guide_text
    assert "codex.discovery.watch" in guide_text
    assert "skills_changed" in guide_text
    assert "apps_updated" in guide_text
    assert "watch-task bridge" in compatibility_text

    for fragment in discovery_contract["task_streaming"]["supported_events"]:
        assert fragment in guide_text


def test_guide_mentions_declared_thread_lifecycle_contract() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()
    lifecycle_contract = build_thread_lifecycle_extension_params(
        runtime_profile=build_runtime_profile(make_settings(a2a_bearer_token="test-token")),
    )

    assert "codex.threads.fork" in guide_text
    assert "codex.threads.archive" in guide_text
    assert "codex.threads.unarchive" in guide_text
    assert "codex.threads.metadata.update" in guide_text
    assert "codex.threads.watch" in guide_text
    assert "codex.threads.watch.release" in guide_text
    assert "thread_started" in guide_text
    assert "thread_status_changed" in guide_text
    assert "thread_archived" in guide_text
    assert "thread_unarchived" in guide_text
    assert "thread_closed" in guide_text
    assert "thread lifecycle watch-task bridge" in compatibility_text
    assert "codex.threads.watch.release" in compatibility_text

    for fragment in lifecycle_contract["task_streaming"]["supported_events"]:
        assert fragment in guide_text


def test_guide_mentions_declared_turn_control_contract() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()

    assert "codex.turns.steer" in guide_text
    assert "active regular turn" in guide_text
    assert "expected_turn_id" in guide_text
    assert "request.parts" in guide_text
    assert "turn-level override fields are intentionally rejected" in guide_text
    assert "codex.turns.*" in compatibility_text


def test_guide_mentions_declared_review_control_contract() -> None:
    guide_text = Path("docs/guide.md").read_text()
    compatibility_text = Path("docs/compatibility.md").read_text()

    assert "codex.review.start" in guide_text
    assert "uncommittedChanges" in guide_text
    assert "baseBranch" in guide_text
    assert "detached" in guide_text
    assert "review watch task bridge" in guide_text
    assert "codex.review.*" in compatibility_text


def test_guide_environment_variables_match_settings_aliases() -> None:
    import re

    from codex_a2a.config import Settings

    guide_text = Path("docs/guide.md").read_text()
    env_section = _extract_heading_section(guide_text, "Environment Variables")
    documented_names = set(re.findall(r"`((?:A2A|CODEX)_[A-Z0-9_]+)`", env_section))

    setting_aliases = {
        field.alias
        for field in Settings.model_fields.values()
        if isinstance(field.alias, str) and field.alias.startswith(("A2A_", "CODEX_"))
    }

    assert documented_names == setting_aliases, (
        "docs/guide.md Environment Variables drifted from Settings aliases."
    )


def test_openapi_jsonrpc_examples_match_declared_extension_contracts() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    post = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]
    extension_contracts = post["x-codex-contracts"]
    session_method_contracts = extension_contracts["session_query"]["method_contracts"]
    discovery_method_contracts = extension_contracts["discovery"]["method_contracts"]
    interrupt_recovery_method_contracts = extension_contracts["interrupt_recovery"][
        "method_contracts"
    ]
    turn_control_method_contracts = extension_contracts["turn_control"]["method_contracts"]
    review_control_method_contracts = extension_contracts["review_control"]["method_contracts"]
    exec_method_contracts = extension_contracts["exec_control"]["method_contracts"]
    thread_lifecycle_method_contracts = extension_contracts["thread_lifecycle"]["method_contracts"]
    interrupt_method_contracts = extension_contracts["interrupt_callback"]["method_contracts"]
    declared_extension_methods = (
        set(session_method_contracts)
        | set(discovery_method_contracts)
        | set(thread_lifecycle_method_contracts)
        | set(interrupt_recovery_method_contracts)
        | set(turn_control_method_contracts)
        | set(review_control_method_contracts)
        | set(exec_method_contracts)
        | set(interrupt_method_contracts)
    )
    examples = post["requestBody"]["content"]["application/json"]["examples"]

    for example in examples.values():
        payload = example["value"]
        method = payload["method"]
        if method in {
            "SendMessage",
            "SendStreamingMessage",
            "GetExtendedAgentCard",
        }:
            continue

        assert method in declared_extension_methods, (
            f"OpenAPI example method {method!r} is not declared by extension contracts."
        )

        params = payload.get("params", {})
        method_contract = (
            session_method_contracts.get(method)
            or discovery_method_contracts.get(method)
            or thread_lifecycle_method_contracts.get(method)
            or interrupt_recovery_method_contracts.get(method)
            or turn_control_method_contracts.get(method)
            or review_control_method_contracts.get(method)
            or exec_method_contracts.get(method)
            or interrupt_method_contracts[method]
        )
        required_fields = method_contract["params"].get("required", [])
        for field in required_fields:
            assert _example_params_include_field(params, field), (
                f"OpenAPI example for {method!r} is missing required field {field!r}."
            )


def test_openapi_jsonrpc_examples_drop_removed_session_control_methods() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    post = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]
    examples = post["requestBody"]["content"]["application/json"]["examples"]
    methods = {example["value"]["method"] for example in examples.values()}
    session_contracts = post["x-codex-contracts"]["session_query"]["method_contracts"]

    assert "codex.sessions.command" not in methods
    assert "codex.sessions.prompt_async" not in methods
    assert "codex.sessions.shell" not in session_contracts
    assert "codex.sessions.command" not in session_contracts
    assert "codex.sessions.prompt_async" not in session_contracts
    assert "control_methods" not in post["x-codex-contracts"]["session_query"]


def test_openapi_exec_examples_declare_task_streaming_contract() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    post = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]
    examples = post["requestBody"]["content"]["application/json"]["examples"]
    exec_contracts = post["x-codex-contracts"]["exec_control"]["method_contracts"]
    streaming_contract = post["x-codex-contracts"]["exec_control"]["task_streaming"]

    assert examples["exec_start"]["value"]["method"] == "codex.exec.start"
    assert examples["exec_write"]["value"]["method"] == "codex.exec.write"
    assert examples["exec_resize"]["value"]["method"] == "codex.exec.resize"
    assert examples["exec_terminate"]["value"]["method"] == "codex.exec.terminate"
    assert exec_contracts["codex.exec.start"]["execution_binding"] == (
        "standalone_interactive_command_exec"
    )
    assert streaming_contract["task_stream_method"] == "SubscribeToTask"
    assert "process_id" in exec_contracts["codex.exec.start"]["result"]["fields"]


def test_openapi_jsonrpc_examples_use_declared_default_session_limit() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    examples = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]

    assert examples["session_list"]["value"]["params"]["limit"] == SESSION_QUERY_DEFAULT_LIMIT
    assert examples["session_messages"]["value"]["params"]["limit"] == SESSION_QUERY_DEFAULT_LIMIT
