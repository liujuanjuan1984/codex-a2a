from pathlib import Path

import httpx
import pytest

from codex_a2a.contracts.extension_registry import build_openapi_extension_contracts_from_registry
from codex_a2a.contracts.extension_specs import (
    ALL_EXTENSION_URIS,
    EXTENSION_SPEC_DOCUMENT_PATHS_BY_URI,
    EXTENSION_URI_NAMESPACE,
)
from codex_a2a.contracts.extensions import (
    COMPATIBILITY_PROFILE_EXTENSION_URI,
    CORE_JSONRPC_PATH,
    DISCOVERY_EXTENSION_URI,
    EXEC_CONTROL_EXTENSION_URI,
    EXTENSION_JSONRPC_PATH,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    INTERRUPT_RECOVERY_EXTENSION_URI,
    REVIEW_CONTROL_EXTENSION_URI,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_EXTENSION_URI,
    STREAMING_EXTENSION_URI,
    THREAD_LIFECYCLE_EXTENSION_URI,
    TURN_CONTROL_EXTENSION_URI,
    WIRE_CONTRACT_EXTENSION_URI,
    build_capability_snapshot,
    build_compatibility_profile_params,
    build_discovery_extension_params,
    build_interrupt_callback_extension_params,
    build_interrupt_recovery_extension_params,
    build_review_control_extension_params,
    build_session_query_extension_params,
    build_streaming_extension_params,
    build_thread_lifecycle_extension_params,
    build_turn_control_extension_params,
    build_wire_contract_extension_params,
)
from codex_a2a.profile.runtime import build_runtime_profile
from codex_a2a.server.agent_card import build_agent_card, build_authenticated_extended_agent_card
from codex_a2a.server.application import create_app
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
    return build_openapi_extension_contracts_from_registry(
        settings=settings,
        runtime_profile=runtime_profile,
        group="codex",
    )


def _public_a2a_contracts(settings) -> dict[str, dict[str, object]]:  # noqa: ANN001
    runtime_profile = build_runtime_profile(settings)
    return build_openapi_extension_contracts_from_registry(
        settings=settings,
        runtime_profile=runtime_profile,
        group="a2a",
        public=True,
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


def test_provider_private_contract_builders_reject_non_1_0_protocol_version() -> None:
    runtime_profile = build_runtime_profile(make_settings(a2a_bearer_token="test-token"))

    with pytest.raises(
        ValueError,
        match="Provider-private codex contracts must stay on the 1.0 protocol line.",
    ):
        build_wire_contract_extension_params(
            protocol_version="2.0",
            runtime_profile=runtime_profile,
        )

    with pytest.raises(
        ValueError,
        match="Provider-private codex contracts must stay on the 1.0 protocol line.",
    ):
        build_compatibility_profile_params(
            protocol_version="0.3",
            runtime_profile=runtime_profile,
        )


def test_machine_readable_contracts_use_canonical_extension_uri_inventory() -> None:
    runtime_profile = build_runtime_profile(make_settings(a2a_bearer_token="test-token"))

    wire_contract = build_wire_contract_extension_params(
        protocol_version="1.0",
        runtime_profile=runtime_profile,
    )
    compatibility_profile = build_compatibility_profile_params(
        protocol_version="1.0",
        runtime_profile=runtime_profile,
    )

    assert wire_contract["extensions"]["extension_uris"] == list(ALL_EXTENSION_URIS)
    assert set(compatibility_profile["extension_retention"]) == set(ALL_EXTENSION_URIS)


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


def test_openapi_jsonrpc_contract_extension_matches_public_ssot() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    app = create_app(settings)
    openapi = app.openapi()
    core_contract = openapi["paths"][CORE_JSONRPC_PATH]["post"].get("x-a2a-extension-contracts")
    assert isinstance(core_contract, dict), (
        "POST / OpenAPI is missing x-a2a-extension-contracts metadata."
    )
    assert openapi["paths"][EXTENSION_JSONRPC_PATH]["post"].get("x-codex-contracts") is None
    assert core_contract == _public_a2a_contracts(settings)


def test_openapi_and_agent_card_contract_partitions_match() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    public_card = build_agent_card(settings)
    card = build_authenticated_extended_agent_card(settings)
    public_ext_by_uri = {ext.uri: ext for ext in public_card.capabilities.extensions or []}
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    openapi = create_app(settings).openapi()
    core_contract = openapi["paths"][CORE_JSONRPC_PATH]["post"]["x-a2a-extension-contracts"]
    assert (
        create_app(settings).openapi()["paths"][CORE_JSONRPC_PATH]["post"].get("x-codex-contracts")
        is None
    )

    assert (
        core_contract["session_binding"] == public_ext_by_uri[SESSION_BINDING_EXTENSION_URI].params
    )
    assert core_contract["streaming"] == public_ext_by_uri[STREAMING_EXTENSION_URI].params
    assert (
        core_contract["interrupt_callback"]
        == public_ext_by_uri[INTERRUPT_CALLBACK_EXTENSION_URI].params
    )
    assert set(ext_by_uri) == {
        SESSION_BINDING_EXTENSION_URI,
        STREAMING_EXTENSION_URI,
        SESSION_QUERY_EXTENSION_URI,
        DISCOVERY_EXTENSION_URI,
        THREAD_LIFECYCLE_EXTENSION_URI,
        INTERRUPT_RECOVERY_EXTENSION_URI,
        TURN_CONTROL_EXTENSION_URI,
        REVIEW_CONTROL_EXTENSION_URI,
        EXEC_CONTROL_EXTENSION_URI,
        INTERRUPT_CALLBACK_EXTENSION_URI,
        WIRE_CONTRACT_EXTENSION_URI,
        COMPATIBILITY_PROFILE_EXTENSION_URI,
    }
    assert (
        ext_by_uri[SESSION_QUERY_EXTENSION_URI].params
        == _codex_contracts(settings)["session_query"]
    )
    assert ext_by_uri[DISCOVERY_EXTENSION_URI].params == _codex_contracts(settings)["discovery"]
    assert (
        ext_by_uri[THREAD_LIFECYCLE_EXTENSION_URI].params
        == _codex_contracts(settings)["thread_lifecycle"]
    )
    assert (
        ext_by_uri[INTERRUPT_RECOVERY_EXTENSION_URI].params
        == _codex_contracts(settings)["interrupt_recovery"]
    )
    assert (
        ext_by_uri[TURN_CONTROL_EXTENSION_URI].params == _codex_contracts(settings)["turn_control"]
    )
    assert (
        ext_by_uri[REVIEW_CONTROL_EXTENSION_URI].params
        == _codex_contracts(settings)["review_control"]
    )
    assert (
        ext_by_uri[EXEC_CONTROL_EXTENSION_URI].params == _codex_contracts(settings)["exec_control"]
    )
    assert ext_by_uri[
        INTERRUPT_CALLBACK_EXTENSION_URI
    ].params == build_interrupt_callback_extension_params(
        runtime_profile=build_runtime_profile(settings)
    )
    assert (
        ext_by_uri[WIRE_CONTRACT_EXTENSION_URI].params
        == _codex_contracts(settings)["wire_contract"]
    )
    assert (
        ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI].params
        == _codex_contracts(settings)["compatibility_profile"]
    )


def test_extension_uris_map_to_repository_spec_index() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    index_path = repo_root / "docs" / "extension-specifications.md"
    index_text = index_path.read_text(encoding="utf-8")

    assert ALL_EXTENSION_URIS == (
        "urn:codex-a2a:extension:session-binding:v1",
        "urn:codex-a2a:extension:stream-hints:v1",
        "urn:codex-a2a:extension:session-query:v1",
        "urn:codex-a2a:extension:discovery:v1",
        "urn:codex-a2a:extension:thread-lifecycle:v1",
        "urn:codex-a2a:extension:interrupt-recovery:v1",
        "urn:codex-a2a:extension:turn-control:v1",
        "urn:codex-a2a:extension:review-control:v1",
        "urn:codex-a2a:extension:exec-control:v1",
        "urn:codex-a2a:extension:interactive-interrupt:v1",
        "urn:codex-a2a:extension:wire-contract:v1",
        "urn:codex-a2a:extension:compatibility-profile:v1",
    )
    spec_paths = {repo_root / path for path in EXTENSION_SPEC_DOCUMENT_PATHS_BY_URI.values()}
    assert spec_paths == {index_path}

    for uri in ALL_EXTENSION_URIS:
        assert uri.startswith(EXTENSION_URI_NAMESPACE), (
            "Extension URI drifted away from the repository-governed permanent URN namespace."
        )
        uri_suffix = uri.removeprefix(EXTENSION_URI_NAMESPACE)
        assert uri_suffix.split(":")[0] not in {"shared", "private"}, (
            "Extension URI must not encode disclosure or auth semantics in the URI path."
        )
        local_spec_path = repo_root / EXTENSION_SPEC_DOCUMENT_PATHS_BY_URI[uri]
        assert local_spec_path.is_file(), (
            f"Extension URI {uri!r} does not map to a checked-in spec document."
        )
        assert uri in index_text


def test_guide_mentions_declared_streaming_contract_fields() -> None:
    guide_text = Path("docs/guide.md").read_text()
    streaming_contract = build_streaming_extension_params()

    required_doc_fragments = [
        streaming_contract["artifact_metadata_field"],
        streaming_contract["session_metadata_field"],
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
        protocol_version="1.0",
        runtime_profile=build_runtime_profile(make_settings(a2a_bearer_token="test-token")),
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
    public_interrupt_contract = post["x-a2a-extension-contracts"]["interrupt_callback"]
    interrupt_method_contracts = build_interrupt_callback_extension_params(
        runtime_profile=build_runtime_profile(settings)
    )["method_contracts"]
    declared_extension_methods = set(public_interrupt_contract["methods"].values())
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
        method_contract = interrupt_method_contracts[method]
        required_fields = method_contract["params"].get("required", [])
        for field in required_fields:
            assert _example_params_include_field(params, field), (
                f"OpenAPI example for {method!r} is missing required field {field!r}."
            )


def test_openapi_jsonrpc_examples_do_not_disclose_provider_private_methods() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    post = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]
    examples = post["requestBody"]["content"]["application/json"]["examples"]
    methods = {example["value"]["method"] for example in examples.values()}

    assert post.get("x-codex-contracts") is None
    assert "codex.sessions.command" not in methods
    assert "codex.sessions.list" not in methods
    assert "codex.discovery.skills.list" not in methods
    assert "codex.exec.start" not in methods
    assert "codex.sessions.prompt_async" not in methods


def test_authenticated_extended_agent_card_keeps_exec_contract_canonical() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    card = build_authenticated_extended_agent_card(settings)
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    exec_contract = ext_by_uri[EXEC_CONTROL_EXTENSION_URI].params
    assert exec_contract is not None
    exec_contracts = exec_contract["method_contracts"]
    streaming_contract = exec_contract["task_streaming"]

    assert exec_contracts["codex.exec.start"]["execution_binding"] == (
        "standalone_interactive_command_exec"
    )
    assert streaming_contract["task_stream_method"] == "SubscribeToTask"
    assert "process_id" in exec_contracts["codex.exec.start"]["result"]["fields"]


def test_public_openapi_omits_provider_private_session_examples() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    openapi = create_app(settings).openapi()
    examples = openapi["paths"][EXTENSION_JSONRPC_PATH]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]

    assert "session_list" not in examples
    assert "session_messages" not in examples
