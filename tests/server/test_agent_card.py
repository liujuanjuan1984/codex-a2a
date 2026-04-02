from codex_a2a.contracts.extensions import (
    COMPATIBILITY_PROFILE_EXTENSION_URI,
    DISCOVERY_EXTENSION_URI,
    EXEC_CONTROL_EXTENSION_URI,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_EXTENSION_URI,
    SESSION_QUERY_MAX_LIMIT,
    STREAMING_EXTENSION_URI,
    THREAD_LIFECYCLE_EXTENSION_URI,
    WIRE_CONTRACT_EXTENSION_URI,
)
from codex_a2a.media_modes import (
    APPLICATION_JSON_MEDIA_MODE,
    DEFAULT_INPUT_MEDIA_MODES,
    DEFAULT_OUTPUT_MEDIA_MODES,
    IMAGE_ANY_MEDIA_MODE,
    TEXT_PLAIN_MEDIA_MODE,
)
from codex_a2a.server.agent_card import (
    build_agent_card,
    build_authenticated_extended_agent_card,
)
from tests.support.settings import make_settings


def test_public_agent_card_description_reflects_discovery_surface() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert "HTTP+JSON and JSON-RPC transports" in card.description
    assert "authenticated extended Agent Card discovery" in card.description
    assert "single-tenant deployment" in card.description.lower()
    assert "machine-readable wire contract" not in card.description
    assert card.supports_authenticated_extended_card is True


def test_authenticated_extended_agent_card_description_reflects_detailed_contracts() -> None:
    card = build_authenticated_extended_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert "message/send, message/stream" in card.description
    assert "tasks/get, tasks/cancel, tasks/resubscribe" in card.description
    assert "agent/getAuthenticatedExtendedCard" in card.description
    assert "interactive exec extensions" in card.description
    assert "machine-readable wire contract" in card.description
    assert "machine-readable compatibility profile" in card.description
    assert "all consumers share the same underlying Codex workspace/environment" in card.description


def test_agent_card_declares_bearer_only_security() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert set((card.security_schemes or {}).keys()) == {"bearerAuth"}
    assert card.security == [{"bearerAuth": []}]


def test_agent_card_declares_media_modes_that_match_runtime_contract() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    skill_by_id = {skill.id: skill for skill in card.skills or []}

    assert card.default_input_modes == DEFAULT_INPUT_MEDIA_MODES
    assert card.default_output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    chat_skill = skill_by_id["codex.chat"]
    assert chat_skill.input_modes == DEFAULT_INPUT_MEDIA_MODES
    assert chat_skill.output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    discovery_skill = skill_by_id["codex.discovery.query"]
    assert discovery_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert discovery_skill.output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    thread_skill = skill_by_id["codex.threads.lifecycle"]
    assert thread_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert thread_skill.output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    assert DEFAULT_INPUT_MEDIA_MODES == [
        TEXT_PLAIN_MEDIA_MODE,
        IMAGE_ANY_MEDIA_MODE,
        APPLICATION_JSON_MEDIA_MODE,
    ]


def test_public_agent_card_minimizes_provider_private_contracts() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}

    session_binding = ext_by_uri[SESSION_BINDING_EXTENSION_URI]
    assert session_binding.params == {
        "metadata_field": "metadata.shared.session.id",
        "behavior": "prefer_metadata_binding_else_create_session",
        "supported_metadata": ["shared.session.id", "codex.directory"],
        "provider_private_metadata": ["codex.directory"],
    }

    streaming = ext_by_uri[STREAMING_EXTENSION_URI]
    assert streaming.params["artifact_metadata_field"] == "metadata.shared.stream"
    assert streaming.params["status_metadata_field"] == "metadata.shared.stream"
    assert streaming.params["interrupt_metadata_field"] == "metadata.shared.interrupt"
    assert streaming.params["session_fields"] == {
        "id": "metadata.shared.session.id",
        "title": "metadata.shared.session.title",
    }
    assert streaming.params["usage_fields"]["total_tokens"] == "metadata.shared.usage.total_tokens"
    assert "tool_call_payload_contract" not in streaming.params

    assert ext_by_uri[SESSION_QUERY_EXTENSION_URI].params is None
    assert ext_by_uri[DISCOVERY_EXTENSION_URI].params is None
    assert ext_by_uri[THREAD_LIFECYCLE_EXTENSION_URI].params is None
    assert ext_by_uri[EXEC_CONTROL_EXTENSION_URI].params is None
    assert ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI].params is None
    assert ext_by_uri[WIRE_CONTRACT_EXTENSION_URI].params is None

    interrupt = ext_by_uri[INTERRUPT_CALLBACK_EXTENSION_URI]
    assert interrupt.params == {
        "methods": {
            "reply_permission": "a2a.interrupt.permission.reply",
            "reply_question": "a2a.interrupt.question.reply",
            "reject_question": "a2a.interrupt.question.reject",
            "reply_permissions": "a2a.interrupt.permissions.reply",
            "reply_elicitation": "a2a.interrupt.elicitation.reply",
        },
        "supported_interrupt_events": [
            "permission.asked",
            "question.asked",
            "permissions.asked",
            "elicitation.asked",
        ],
        "request_id_field": "metadata.shared.interrupt.request_id",
    }


def test_authenticated_extended_agent_card_injects_profile_into_extensions() -> None:
    card = build_authenticated_extended_agent_card(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_project="alpha",
            codex_workspace_root="/srv/workspaces/alpha",
            codex_provider_id="google",
            codex_model_id="gemini-2.5-flash",
            codex_agent="code-reviewer",
            codex_variant="safe",
            a2a_allow_directory_override=False,
            a2a_execution_sandbox_mode="workspace-write",
            a2a_execution_network_access="restricted",
            a2a_execution_network_allowed_domains=["api.openai.com"],
            a2a_execution_approval_policy="on-request",
            a2a_execution_write_access_scope="workspace_root_or_descendant",
        )
    )
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}

    binding = ext_by_uri[SESSION_BINDING_EXTENSION_URI]
    profile = binding.params["profile"]
    assert profile["profile_id"] == "codex-a2a-single-tenant-coding-v1"
    assert profile["deployment"] == {
        "id": "single_tenant_shared_workspace",
        "single_tenant": True,
        "shared_workspace_across_consumers": True,
        "tenant_isolation": "none",
    }
    assert profile["runtime_context"] == {
        "project": "alpha",
        "workspace_root": "/srv/workspaces/alpha",
        "provider_id": "google",
        "model_id": "gemini-2.5-flash",
        "agent": "code-reviewer",
        "variant": "safe",
    }
    assert profile["runtime_features"]["directory_binding"] == {
        "allow_override": False,
        "scope": "workspace_root_only",
    }
    assert profile["runtime_features"]["session_shell"] == {
        "enabled": True,
        "availability": "enabled",
        "toggle": "A2A_ENABLE_SESSION_SHELL",
    }
    assert profile["runtime_features"]["interrupts"] == {
        "request_ttl_seconds": 3600,
    }
    assert profile["runtime_features"]["execution_environment"] == {
        "sandbox": {
            "mode": "workspace-write",
            "filesystem_scope": "workspace_root_or_descendant",
        },
        "network": {
            "access": "restricted",
            "allowed_domains": ["api.openai.com"],
        },
        "approval": {
            "policy": "on-request",
            "escalation_behavior": "per_request",
        },
        "write_access": {
            "scope": "workspace_root_or_descendant",
            "outside_workspace": False,
        },
    }
    assert binding.params["metadata_field"] == "metadata.shared.session.id"
    assert binding.params["supported_metadata"] == [
        "shared.session.id",
        "codex.directory",
    ]
    assert binding.params["provider_private_metadata"] == ["codex.directory"]

    streaming = ext_by_uri[STREAMING_EXTENSION_URI]
    assert streaming.params["artifact_metadata_field"] == "metadata.shared.stream"
    assert streaming.params["interrupt_metadata_field"] == "metadata.shared.interrupt"
    assert streaming.params["session_metadata_field"] == "metadata.shared.session"
    assert streaming.params["usage_metadata_field"] == "metadata.shared.usage"
    assert streaming.params["block_part_types"] == {
        "text": "TextPart",
        "reasoning": "TextPart",
        "tool_call": "DataPart",
    }
    assert streaming.params["stream_fields"]["sequence"] == "metadata.shared.stream.sequence"
    assert streaming.params["status_stream_fields"]["event_id"] == "metadata.shared.stream.event_id"
    assert streaming.params["session_fields"]["title"] == "metadata.shared.session.title"
    assert streaming.params["interrupt_fields"]["phase"] == "metadata.shared.interrupt.phase"
    assert (
        streaming.params["interrupt_fields"]["resolution"] == "metadata.shared.interrupt.resolution"
    )
    assert (
        streaming.params["usage_fields"]["reasoning_tokens"]
        == "metadata.shared.usage.reasoning_tokens"
    )
    assert (
        streaming.params["usage_fields"]["cache_read_tokens"]
        == "metadata.shared.usage.cache_tokens.read_tokens"
    )
    assert streaming.params["usage_fields"]["raw"] == "metadata.shared.usage.raw"
    assert streaming.params["artifact_stream_contract"]["required_fields"] == [
        "block_type",
        "source",
    ]
    assert streaming.params["status_stream_contract"]["required_fields"] == ["source"]
    assert streaming.params["session_contract"]["required_fields"] == ["id"]
    assert streaming.params["interrupt_contract"]["open_object_fields"] == ["details"]
    assert streaming.params["usage_contract"]["nested_objects"]["cache_tokens"] == {
        "required_fields": [],
        "optional_fields": ["read_tokens", "write_tokens"],
    }
    tool_call_contract = streaming.params["tool_call_payload_contract"]
    assert tool_call_contract["a2a_part_type"] == "DataPart"
    assert tool_call_contract["discriminator"] == {
        "field": "kind",
        "allowed_values": ["state", "output_delta"],
    }
    assert tool_call_contract["variants"]["state"]["suppressed_when_only_fields"] == ["kind"]
    assert tool_call_contract["variants"]["output_delta"]["output_delta_rules"] == {
        "type": "string",
        "empty_string": "rejected",
        "preserve_verbatim": True,
    }

    session_query = ext_by_uri[SESSION_QUERY_EXTENSION_URI]
    assert session_query.params["profile"] == profile
    assert session_query.params["supported_metadata"] == ["codex.directory"]
    assert session_query.params["provider_private_metadata"] == ["codex.directory"]
    assert session_query.params["pagination"]["mode"] == "limit"
    assert session_query.params["pagination"]["default_limit"] == SESSION_QUERY_DEFAULT_LIMIT
    assert session_query.params["pagination"]["max_limit"] == SESSION_QUERY_MAX_LIMIT
    assert session_query.params["pagination"]["behavior"] == "mixed"
    assert session_query.params["pagination"]["by_method"] == {
        "codex.sessions.list": "upstream_passthrough",
        "codex.sessions.messages.list": "local_tail_slice",
    }
    assert session_query.params["rich_input"]["prompt_async_part_types"] == [
        "text",
        "image",
        "mention",
        "skill",
    ]
    assert session_query.params["rich_input"]["core_message_part_mapping"] == {
        "TextPart": "text",
        "FilePart(image only)": "input_image",
        "DataPart(type=mention|skill)": "mention|skill",
    }
    assert (
        session_query.params["rich_input"]["prompt_async_part_contracts"]["image"]["maps_to"]
        == "turn/start.input[].type=input_image"
    )
    assert any(
        "mention.path values are forwarded verbatim" in note
        for note in session_query.params["rich_input"]["notes"]
    )
    assert session_query.params["result_envelope"] == {}
    assert any(
        "forwards limit upstream" in note for note in session_query.params["pagination"]["notes"]
    )
    assert (
        session_query.params["context_semantics"]["upstream_session_id_field"]
        == "metadata.shared.session.id"
    )
    assert session_query.params["context_semantics"]["context_id_strategy"] == (
        "equals_upstream_session_id"
    )
    assert any(
        "contextId equal to the upstream session_id" in note
        for note in session_query.params["context_semantics"]["notes"]
    )
    shell_contract = session_query.params["method_contracts"]["codex.sessions.shell"]
    assert shell_contract["execution_binding"] == "standalone_command_exec"
    assert shell_contract["session_binding"] == "ownership_attribution_only"
    assert shell_contract["uses_upstream_session_context"] is False
    assert any("command/exec" in note for note in shell_contract["notes"])
    assert any("one-shot shell snapshot" in note for note in shell_contract["notes"])
    prompt_contract = session_query.params["method_contracts"]["codex.sessions.prompt_async"]
    assert any("type=text, image, mention, and skill" in note for note in prompt_contract["notes"])
    assert any("local_image" in note for note in prompt_contract["notes"])

    discovery = ext_by_uri[DISCOVERY_EXTENSION_URI]
    assert discovery.params["profile"] == profile
    assert discovery.params["methods"]["list_skills"] == "codex.discovery.skills.list"
    assert discovery.params["methods"]["list_apps"] == "codex.discovery.apps.list"
    assert discovery.params["methods"]["list_plugins"] == "codex.discovery.plugins.list"
    assert discovery.params["methods"]["read_plugin"] == "codex.discovery.plugins.read"
    assert discovery.params["notification_bridge"]["current_delivery"] == (
        "codex.discovery.watch task stream"
    )
    assert "mention_path" in discovery.params["stable_item_fields"]["app"]
    apps_contract = discovery.params["method_contracts"]["codex.discovery.apps.list"]
    assert apps_contract["result"]["fields"] == ["items", "next_cursor"]
    assert any("mention_path" in note for note in apps_contract["notes"])

    thread_lifecycle = ext_by_uri[THREAD_LIFECYCLE_EXTENSION_URI]
    assert thread_lifecycle.params["profile"] == profile
    assert thread_lifecycle.params["methods"]["fork"] == "codex.threads.fork"
    assert thread_lifecycle.params["methods"]["archive"] == "codex.threads.archive"
    assert thread_lifecycle.params["methods"]["unarchive"] == "codex.threads.unarchive"
    assert thread_lifecycle.params["methods"]["metadata_update"] == "codex.threads.metadata.update"
    assert thread_lifecycle.params["methods"]["watch"] == "codex.threads.watch"
    assert thread_lifecycle.params["notification_bridge"]["current_delivery"] == (
        "codex.threads.watch task stream"
    )
    assert thread_lifecycle.params["task_streaming"]["task_stream_method"] == "tasks/resubscribe"
    assert thread_lifecycle.params["stable_thread_fields"] == ["id", "title", "status", "codex.raw"]
    assert any(
        "thread/unsubscribe is intentionally excluded" in note
        for note in thread_lifecycle.params["notification_bridge"]["notes"]
    )
    assert (
        thread_lifecycle.params["method_contracts"]["codex.threads.watch"][
            "notification_response_status"
        ]
        == 204
    )

    interrupt = ext_by_uri[INTERRUPT_CALLBACK_EXTENSION_URI]
    assert interrupt.params["profile"] == profile
    assert interrupt.params["request_id_field"] == "metadata.shared.interrupt.request_id"
    assert interrupt.params["supported_metadata"] == ["codex.directory"]
    assert interrupt.params["provider_private_metadata"] == ["codex.directory"]
    assert interrupt.params["methods"]["reply_permissions"] == "a2a.interrupt.permissions.reply"
    assert interrupt.params["methods"]["reply_elicitation"] == "a2a.interrupt.elicitation.reply"
    assert "permissions.asked" in interrupt.params["supported_interrupt_events"]
    assert "elicitation.asked" in interrupt.params["supported_interrupt_events"]
    assert interrupt.params["permissions_reply_contract"]["scope"] == (
        "optional persistence scope: turn or session"
    )
    assert interrupt.params["elicitation_reply_contract"]["action"] == (
        "accept, decline, or cancel"
    )
    assert interrupt.params["errors"]["business_codes"]["INTERRUPT_REQUEST_EXPIRED"] == -32007
    assert interrupt.params["errors"]["business_codes"]["INTERRUPT_TYPE_MISMATCH"] == -32008
    assert "expected_interrupt_type" in interrupt.params["errors"]["error_data_fields"]
    assert "actual_interrupt_type" in interrupt.params["errors"]["error_data_fields"]

    exec_control = ext_by_uri[EXEC_CONTROL_EXTENSION_URI]
    assert exec_control.params["profile"] == profile
    assert exec_control.params["supported_metadata"] == ["codex.directory"]
    assert exec_control.params["provider_private_metadata"] == ["codex.directory"]
    assert exec_control.params["task_streaming"]["task_stream_method"] == "tasks/resubscribe"
    start_contract = exec_control.params["method_contracts"]["codex.exec.start"]
    assert start_contract["execution_binding"] == "standalone_interactive_command_exec"
    assert start_contract["result"]["fields"] == ["ok", "task_id", "context_id", "process_id"]
    assert any("codex.sessions.shell" in note for note in start_contract["notes"])

    wire_contract = ext_by_uri[WIRE_CONTRACT_EXTENSION_URI]
    assert wire_contract.params["protocol_version"] == "0.3.0"
    assert "agent/getAuthenticatedExtendedCard" in wire_contract.params["all_jsonrpc_methods"]
    assert "tasks/pushNotificationConfig/set" in wire_contract.params["all_jsonrpc_methods"]
    assert "POST /v1/message:send" in wire_contract.params["core"]["http_endpoints"]
    assert "GET /v1/card" in wire_contract.params["core"]["http_endpoints"]

    compatibility = ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI]
    assert compatibility.params["profile_id"] == "codex-a2a-single-tenant-coding-v1"
    assert compatibility.params["protocol_version"] == "0.3.0"
    assert compatibility.params["deployment"] == profile["deployment"]
    assert compatibility.params["runtime_features"] == profile["runtime_features"]
    assert "agent/getAuthenticatedExtendedCard" in compatibility.params["core"]["jsonrpc_methods"]
    assert compatibility.params["extension_taxonomy"]["provider_private_metadata"] == [
        "codex.directory"
    ]
    assert compatibility.params["method_retention"]["agent/getAuthenticatedExtendedCard"] == {
        "surface": "core",
        "availability": "always",
        "retention": "required",
    }
    assert compatibility.params["method_retention"]["tasks/pushNotificationConfig/set"] == {
        "surface": "core",
        "availability": "always",
        "retention": "required",
    }
    assert any(
        "single-tenant, shared-workspace coding profile" in note
        for note in compatibility.params["consumer_guidance"]
    )
    assert any("urn:a2a:*" in note for note in compatibility.params["consumer_guidance"])
    assert any(
        "execution_environment" in note for note in compatibility.params["consumer_guidance"]
    )
    assert any(
        "terminal tasks/resubscribe replay-once behavior" in note
        for note in compatibility.params["consumer_guidance"]
    )
    assert any("codex.threads.*" in note for note in compatibility.params["consumer_guidance"])
    assert any("codex.exec.*" in note for note in compatibility.params["consumer_guidance"])
    shell_policy = compatibility.params["method_retention"]["codex.sessions.shell"]
    assert shell_policy["availability"] == "enabled"
    assert shell_policy["retention"] == "deployment-conditional"
    assert shell_policy["toggle"] == "A2A_ENABLE_SESSION_SHELL"
    exec_policy = compatibility.params["method_retention"]["codex.exec.start"]
    assert exec_policy["availability"] == "always"
    assert exec_policy["retention"] == "stable"
    assert exec_policy["extension_uri"] == "urn:codex-a2a:codex-exec/v1"
    thread_policy = compatibility.params["method_retention"]["codex.threads.watch"]
    assert thread_policy["availability"] == "always"
    assert thread_policy["retention"] == "stable"
    assert thread_policy["extension_uri"] == "urn:codex-a2a:codex-thread-lifecycle/v1"


def test_authenticated_extended_agent_card_chat_examples_include_project_hint_when_configured() -> (
    None
):
    card = build_authenticated_extended_agent_card(
        make_settings(a2a_bearer_token="test-token", a2a_project="alpha")
    )
    chat_skill = next(skill for skill in card.skills if skill.id == "codex.chat")
    assert any("project alpha" in example for example in chat_skill.examples)


def test_public_agent_card_skills_are_minimal() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    session_skill = next(skill for skill in card.skills if skill.id == "codex.sessions.query")
    thread_skill = next(skill for skill in card.skills if skill.id == "codex.threads.lifecycle")

    assert session_skill.examples is None
    assert "provider-private" in session_skill.tags
    assert thread_skill.examples is None
    assert "provider-private" in thread_skill.tags


def test_authenticated_extended_agent_card_omits_shell_method_when_disabled() -> None:
    card = build_authenticated_extended_agent_card(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_enable_session_shell=False,
            a2a_interrupt_request_ttl_seconds=45,
        )
    )
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    session_query = ext_by_uri[SESSION_QUERY_EXTENSION_URI]

    assert "shell" not in session_query.params["methods"]
    assert "shell" not in session_query.params["control_methods"]
    assert "codex.sessions.shell" not in session_query.params["method_contracts"]
    assert session_query.params["profile"]["runtime_features"]["session_shell"] == {
        "enabled": False,
        "availability": "disabled",
        "toggle": "A2A_ENABLE_SESSION_SHELL",
    }
    assert session_query.params["profile"]["runtime_features"]["interrupts"] == {
        "request_ttl_seconds": 45
    }
    assert session_query.params["profile"]["runtime_features"]["execution_environment"] == {
        "sandbox": {
            "mode": "unknown",
            "filesystem_scope": "unknown",
        },
        "network": {
            "access": "unknown",
        },
        "approval": {
            "policy": "unknown",
        },
        "write_access": {
            "scope": "unknown",
        },
    }
    wire_contract = ext_by_uri[WIRE_CONTRACT_EXTENSION_URI]
    assert "codex.sessions.shell" not in wire_contract.params["all_jsonrpc_methods"]
    assert wire_contract.params["extensions"]["conditionally_available_methods"] == {
        "codex.sessions.shell": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_SESSION_SHELL",
        }
    }
    compatibility = ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI]
    shell_policy = compatibility.params["method_retention"]["codex.sessions.shell"]
    assert shell_policy["availability"] == "disabled"
    assert compatibility.params["runtime_features"]["session_shell"] == {
        "enabled": False,
        "availability": "disabled",
        "toggle": "A2A_ENABLE_SESSION_SHELL",
    }
