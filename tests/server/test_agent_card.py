from typing import Any

from a2a.types import AgentExtension, AgentSkill

from codex_a2a.a2a_proto import proto_to_python
from codex_a2a.contracts.extensions import (
    COMPATIBILITY_PROFILE_EXTENSION_URI,
    CORE_JSONRPC_PATH,
    DISCOVERY_EXTENSION_URI,
    EXEC_CONTROL_EXTENSION_URI,
    EXTENSION_JSONRPC_PATH,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    INTERRUPT_RECOVERY_EXTENSION_URI,
    REST_API_PATH_PREFIX,
    REVIEW_CONTROL_EXTENSION_URI,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_EXTENSION_URI,
    SESSION_QUERY_MAX_LIMIT,
    STREAMING_EXTENSION_URI,
    THREAD_LIFECYCLE_EXTENSION_URI,
    TURN_CONTROL_EXTENSION_URI,
    WIRE_CONTRACT_EXTENSION_URI,
)
from codex_a2a.media_modes import (
    APPLICATION_JSON_MEDIA_MODE,
    DEFAULT_INPUT_MEDIA_MODES,
    DEFAULT_OUTPUT_MEDIA_MODES,
    IMAGE_ANY_MEDIA_MODE,
    JSON_OUTPUT_MEDIA_MODES,
    TEXT_OUTPUT_MEDIA_MODES,
    TEXT_PLAIN_MEDIA_MODE,
)
from codex_a2a.server.agent_card import (
    build_agent_card,
    build_authenticated_extended_agent_card,
)
from tests.support.settings import make_settings


def _require_params(extension: AgentExtension) -> dict[str, Any]:
    assert extension.params is not None
    params = proto_to_python(extension.params)
    assert isinstance(params, dict)
    return params


def _extension_params(extension: AgentExtension) -> dict[str, Any]:
    params = proto_to_python(extension.params)
    if not isinstance(params, dict):
        return {}
    return params


def _security_requirements(card) -> list[dict[str, Any]]:  # noqa: ANN001
    requirements = proto_to_python(card.security_requirements)
    assert isinstance(requirements, list)
    return requirements


def _require_examples(skill: AgentSkill) -> list[str]:
    assert skill.examples is not None
    return skill.examples


def test_public_agent_card_description_reflects_discovery_surface() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert "HTTP+JSON and JSON-RPC transports" in card.description
    assert "authenticated extended Agent Card discovery" in card.description
    assert "single-tenant deployment" in card.description.lower()
    assert "machine-readable wire contract" not in card.description
    assert card.capabilities.extended_agent_card is True


def test_authenticated_extended_agent_card_description_reflects_detailed_contracts() -> None:
    card = build_authenticated_extended_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert "SendMessage, SendStreamingMessage" in card.description
    assert "GetTask, ListTasks, CancelTask, SubscribeToTask" in card.description
    assert "GetExtendedAgentCard" in card.description
    assert "interactive exec extensions" in card.description
    assert "active-turn control" in card.description
    assert "review control" in card.description
    assert "machine-readable wire contract" in card.description
    assert "machine-readable compatibility profile" in card.description
    assert "all consumers share the same underlying Codex workspace/environment" in card.description


def test_agent_card_declares_bearer_only_security() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))

    assert set((card.security_schemes or {}).keys()) == {"bearerAuth"}
    assert _security_requirements(card) == [{"schemes": {"bearerAuth": {}}}]


def test_agent_card_declares_bearer_and_basic_security_when_configured() -> None:
    card = build_agent_card(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_basic_auth_username="operator",
            a2a_basic_auth_password="op-pass",  # pragma: allowlist secret
        )
    )

    assert set((card.security_schemes or {}).keys()) == {"bearerAuth", "basicAuth"}
    assert _security_requirements(card) == [
        {"schemes": {"bearerAuth": {}}},
        {"schemes": {"basicAuth": {}}},
    ]


def test_agent_card_declares_basic_only_security_when_configured_without_bearer() -> None:
    card = build_agent_card(
        make_settings(
            a2a_bearer_token=None,
            a2a_basic_auth_username="operator",
            a2a_basic_auth_password="op-pass",  # pragma: allowlist secret
        )
    )

    assert set((card.security_schemes or {}).keys()) == {"basicAuth"}
    assert _security_requirements(card) == [{"schemes": {"basicAuth": {}}}]


def test_agent_card_declares_registry_auth_schemes() -> None:
    card = build_agent_card(
        make_settings(
            a2a_bearer_token=None,
            a2a_static_auth_credentials=(
                {
                    "scheme": "bearer",
                    "token": "token-alpha",
                    "principal": "automation-alpha",
                },
                {
                    "scheme": "basic",
                    "username": "ops",
                    "password": "ops-pass",  # pragma: allowlist secret
                },
            ),
        )
    )

    assert set((card.security_schemes or {}).keys()) == {"bearerAuth", "basicAuth"}
    assert _security_requirements(card) == [
        {"schemes": {"bearerAuth": {}}},
        {"schemes": {"basicAuth": {}}},
    ]


def test_agent_card_declares_media_modes_that_match_runtime_contract() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    skill_by_id = {skill.id: skill for skill in card.skills or []}

    assert card.default_input_modes == DEFAULT_INPUT_MEDIA_MODES
    assert card.default_output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    chat_skill = skill_by_id["codex.chat"]
    assert chat_skill.input_modes == DEFAULT_INPUT_MEDIA_MODES
    assert chat_skill.output_modes == DEFAULT_OUTPUT_MEDIA_MODES

    sessions_query_skill = skill_by_id["codex.sessions.query"]
    assert sessions_query_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert sessions_query_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    discovery_skill = skill_by_id["codex.discovery.query"]
    assert discovery_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert discovery_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    discovery_watch_skill = skill_by_id["codex.discovery.watch"]
    assert discovery_watch_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert discovery_watch_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    thread_control_skill = skill_by_id["codex.threads.control"]
    assert thread_control_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert thread_control_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    thread_watch_skill = skill_by_id["codex.threads.watch"]
    assert thread_watch_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert thread_watch_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    turn_control_skill = skill_by_id["codex.turns.control"]
    assert turn_control_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert turn_control_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    review_control_skill = skill_by_id["codex.review.control"]
    assert review_control_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert review_control_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    review_watch_skill = skill_by_id["codex.review.watch"]
    assert review_watch_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert review_watch_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    interrupt_recovery_skill = skill_by_id["codex.interrupt.recovery"]
    assert interrupt_recovery_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert interrupt_recovery_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    interrupt_skill = skill_by_id["codex.interrupt.callback"]
    assert interrupt_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert interrupt_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    exec_control_skill = skill_by_id["codex.exec.control"]
    assert exec_control_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert exec_control_skill.output_modes == JSON_OUTPUT_MEDIA_MODES

    exec_stream_skill = skill_by_id["codex.exec.stream"]
    assert exec_stream_skill.input_modes == [APPLICATION_JSON_MEDIA_MODE]
    assert exec_stream_skill.output_modes == TEXT_OUTPUT_MEDIA_MODES

    assert DEFAULT_INPUT_MEDIA_MODES == [
        TEXT_PLAIN_MEDIA_MODE,
        IMAGE_ANY_MEDIA_MODE,
        APPLICATION_JSON_MEDIA_MODE,
    ]


def test_public_agent_card_minimizes_provider_private_contracts() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}

    session_binding = ext_by_uri[SESSION_BINDING_EXTENSION_URI]
    session_binding_params = _require_params(session_binding)
    assert session_binding_params == {
        "metadata_field": "metadata.shared.session.id",
        "behavior": "prefer_metadata_binding_else_create_session",
        "supported_metadata": ["shared.session.id", "codex.directory", "codex.execution"],
        "provider_private_metadata": ["codex.directory", "codex.execution"],
    }

    streaming = ext_by_uri[STREAMING_EXTENSION_URI]
    streaming_params = _require_params(streaming)
    assert streaming_params["artifact_metadata_field"] == "metadata.shared.stream"
    assert streaming_params["status_metadata_field"] == "metadata.shared.stream"
    assert streaming_params["interrupt_metadata_field"] == "metadata.shared.interrupt"
    assert streaming_params["session_fields"] == {
        "id": "metadata.shared.session.id",
        "title": "metadata.shared.session.title",
    }
    assert streaming_params["usage_fields"]["total_tokens"] == "metadata.shared.usage.total_tokens"
    assert "tool_call_payload_contract" not in streaming_params

    assert _extension_params(ext_by_uri[SESSION_QUERY_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[DISCOVERY_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[THREAD_LIFECYCLE_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[TURN_CONTROL_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[REVIEW_CONTROL_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[EXEC_CONTROL_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI]) == {}
    assert _extension_params(ext_by_uri[WIRE_CONTRACT_EXTENSION_URI]) == {}

    interrupt_recovery = ext_by_uri[INTERRUPT_RECOVERY_EXTENSION_URI]
    interrupt_recovery_params = _require_params(interrupt_recovery)
    assert interrupt_recovery_params == {
        "methods": {"list": "codex.interrupts.list"},
        "supported_interrupt_types": [
            "permission",
            "question",
            "permissions",
            "elicitation",
        ],
        "identity_scope": "authenticated_caller",
    }

    interrupt = ext_by_uri[INTERRUPT_CALLBACK_EXTENSION_URI]
    interrupt_params = _require_params(interrupt)
    assert interrupt_params == {
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
    binding_params = _require_params(binding)
    profile = binding_params["profile"]
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
    assert profile["runtime_features"]["turn_control"] == {
        "enabled": True,
        "availability": "enabled",
        "toggle": "A2A_ENABLE_TURN_CONTROL",
    }
    assert profile["runtime_features"]["review_control"] == {
        "enabled": True,
        "availability": "enabled",
        "toggle": "A2A_ENABLE_REVIEW_CONTROL",
    }
    assert profile["runtime_features"]["exec_control"] == {
        "enabled": True,
        "availability": "enabled",
        "toggle": "A2A_ENABLE_EXEC_CONTROL",
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
    assert binding_params["metadata_field"] == "metadata.shared.session.id"
    assert binding_params["supported_metadata"] == [
        "shared.session.id",
        "codex.directory",
        "codex.execution",
    ]
    assert binding_params["provider_private_metadata"] == ["codex.directory", "codex.execution"]
    assert binding_params["request_execution_options"] == {
        "metadata_field": "metadata.codex.execution",
        "fields": ["model", "effort", "summary", "personality"],
        "persists_for_thread": True,
        "notes": [
            (
                "execution.model, execution.effort, execution.summary, and "
                "execution.personality map to upstream thread/start or turn/start "
                "overrides when the selected method starts or continues a turn."
            ),
            (
                "directory remains a separate metadata.codex.directory override so "
                "existing clients do not need to migrate cwd handling."
            ),
        ],
    }

    streaming = ext_by_uri[STREAMING_EXTENSION_URI]
    streaming_params = _require_params(streaming)
    assert streaming_params["artifact_metadata_field"] == "metadata.shared.stream"
    assert streaming_params["interrupt_metadata_field"] == "metadata.shared.interrupt"
    assert streaming_params["session_metadata_field"] == "metadata.shared.session"
    assert streaming_params["usage_metadata_field"] == "metadata.shared.usage"
    assert streaming_params["block_part_types"] == {
        "text": "Part(text)",
        "reasoning": "Part(text)",
        "tool_call": "Part(data)",
    }
    assert streaming_params["stream_fields"]["sequence"] == "metadata.shared.stream.sequence"
    assert streaming_params["status_stream_fields"]["event_id"] == "metadata.shared.stream.event_id"
    assert streaming_params["session_fields"]["title"] == "metadata.shared.session.title"
    assert streaming_params["interrupt_fields"]["phase"] == "metadata.shared.interrupt.phase"
    assert (
        streaming_params["interrupt_fields"]["resolution"] == "metadata.shared.interrupt.resolution"
    )
    assert (
        streaming_params["usage_fields"]["reasoning_tokens"]
        == "metadata.shared.usage.reasoning_tokens"
    )
    assert (
        streaming_params["usage_fields"]["cache_read_tokens"]
        == "metadata.shared.usage.cache_tokens.read_tokens"
    )
    assert streaming_params["usage_fields"]["raw"] == "metadata.shared.usage.raw"
    assert streaming_params["artifact_stream_contract"]["required_fields"] == [
        "block_type",
        "source",
    ]
    assert streaming_params["status_stream_contract"]["required_fields"] == ["source"]
    assert streaming_params["session_contract"]["required_fields"] == ["id"]
    assert streaming_params["interrupt_contract"]["open_object_fields"] == ["details"]
    assert streaming_params["usage_contract"]["nested_objects"]["cache_tokens"] == {
        "required_fields": [],
        "optional_fields": ["read_tokens", "write_tokens"],
    }
    tool_call_contract = streaming_params["tool_call_payload_contract"]
    assert tool_call_contract["a2a_part_type"] == "Part(data)"
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
    session_query_params = _require_params(session_query)
    assert session_query_params["jsonrpc_endpoint"] == {
        "protocol_binding": "JSON-RPC",
        "url_path": EXTENSION_JSONRPC_PATH,
    }
    assert session_query_params["profile"] == profile
    assert session_query_params["supported_metadata"] == ["codex.directory", "codex.execution"]
    assert session_query_params["provider_private_metadata"] == [
        "codex.directory",
        "codex.execution",
    ]
    assert (
        session_query_params["request_execution_options"]
        == binding_params["request_execution_options"]
    )
    assert session_query_params["pagination"]["mode"] == "limit"
    assert session_query_params["pagination"]["default_limit"] == SESSION_QUERY_DEFAULT_LIMIT
    assert session_query_params["pagination"]["max_limit"] == SESSION_QUERY_MAX_LIMIT
    assert session_query_params["pagination"]["behavior"] == "mixed"
    assert session_query_params["pagination"]["by_method"] == {
        "codex.sessions.list": "upstream_passthrough",
        "codex.sessions.messages.list": "local_tail_slice",
    }
    assert session_query_params["rich_input"]["supported_part_types"] == [
        "text",
        "image",
        "mention",
        "skill",
    ]
    assert session_query_params["rich_input"]["core_message_part_mapping"] == {
        "Part(text)": "text",
        "Part(url|raw image only)": "input_image",
        "Part(data mention|skill payloads)": "mention|skill",
    }
    assert (
        session_query_params["rich_input"]["part_contracts"]["image"]["maps_to"]
        == "turn/start.input[].type=input_image"
    )
    assert any(
        "mention.path values are forwarded verbatim" in note
        for note in session_query_params["rich_input"]["notes"]
    )
    assert "control_methods" not in session_query_params
    assert session_query_params["result_envelope"] == {}
    assert any(
        "forwards limit upstream" in note for note in session_query_params["pagination"]["notes"]
    )
    assert (
        session_query_params["context_semantics"]["upstream_session_id_field"]
        == "metadata.shared.session.id"
    )
    assert session_query_params["context_semantics"]["context_id_strategy"] == (
        "equals_upstream_session_id"
    )
    assert any(
        "contextId equal to the upstream session_id" in note
        for note in session_query_params["context_semantics"]["notes"]
    )
    assert "codex.sessions.shell" not in session_query_params["method_contracts"]
    assert "codex.sessions.prompt_async" not in session_query_params["method_contracts"]
    assert "codex.sessions.command" not in session_query_params["method_contracts"]

    discovery = ext_by_uri[DISCOVERY_EXTENSION_URI]
    discovery_params = _require_params(discovery)
    assert discovery_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert discovery_params["profile"] == profile
    assert discovery_params["methods"]["list_skills"] == "codex.discovery.skills.list"
    assert discovery_params["methods"]["list_apps"] == "codex.discovery.apps.list"
    assert discovery_params["methods"]["list_plugins"] == "codex.discovery.plugins.list"
    assert discovery_params["methods"]["read_plugin"] == "codex.discovery.plugins.read"
    assert discovery_params["notification_bridge"]["current_delivery"] == (
        "codex.discovery.watch task stream"
    )
    assert "mention_path" in discovery_params["stable_item_fields"]["app"]
    apps_contract = discovery_params["method_contracts"]["codex.discovery.apps.list"]
    assert apps_contract["result"]["fields"] == ["items", "next_cursor"]
    assert any("mention_path" in note for note in apps_contract["notes"])

    thread_lifecycle = ext_by_uri[THREAD_LIFECYCLE_EXTENSION_URI]
    thread_lifecycle_params = _require_params(thread_lifecycle)
    assert thread_lifecycle_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert thread_lifecycle_params["profile"] == profile
    assert thread_lifecycle_params["methods"]["fork"] == "codex.threads.fork"
    assert thread_lifecycle_params["methods"]["archive"] == "codex.threads.archive"
    assert thread_lifecycle_params["methods"]["unarchive"] == "codex.threads.unarchive"
    assert thread_lifecycle_params["methods"]["metadata_update"] == "codex.threads.metadata.update"
    assert thread_lifecycle_params["methods"]["watch"] == "codex.threads.watch"
    assert thread_lifecycle_params["methods"]["watch_release"] == "codex.threads.watch.release"
    assert thread_lifecycle_params["notification_bridge"]["current_delivery"] == (
        "codex.threads.watch task stream"
    )
    assert thread_lifecycle_params["task_streaming"]["task_stream_method"] == "SubscribeToTask"
    assert thread_lifecycle_params["stable_thread_fields"] == [
        "id",
        "title",
        "status",
        "codex.raw",
    ]
    assert any(
        "thread/unsubscribe is intentionally excluded" in note
        for note in thread_lifecycle_params["notification_bridge"]["notes"]
    )
    assert (
        thread_lifecycle_params["method_contracts"]["codex.threads.watch"][
            "notification_response_status"
        ]
        == 204
    )
    assert (
        thread_lifecycle_params["method_contracts"]["codex.threads.watch.release"][
            "notification_response_status"
        ]
        == 204
    )

    interrupt_recovery = ext_by_uri[INTERRUPT_RECOVERY_EXTENSION_URI]
    interrupt_recovery_params = _require_params(interrupt_recovery)
    assert interrupt_recovery_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert interrupt_recovery_params["profile"] == profile
    assert interrupt_recovery_params["methods"]["list"] == "codex.interrupts.list"
    assert interrupt_recovery_params["supported_interrupt_types"] == [
        "permission",
        "question",
        "permissions",
        "elicitation",
    ]
    assert interrupt_recovery_params["identity_scope"] == "authenticated_caller"
    assert interrupt_recovery_params["result_item_fields"] == [
        "request_id",
        "interrupt_type",
        "session_id",
        "task_id",
        "context_id",
        "created_at",
        "expires_at",
        "properties",
    ]

    turn_control = ext_by_uri[TURN_CONTROL_EXTENSION_URI]
    turn_control_params = _require_params(turn_control)
    assert turn_control_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert turn_control_params["profile"] == profile
    assert turn_control_params["methods"]["steer"] == "codex.turns.steer"
    assert turn_control_params["authorization"]["required_capabilities"] == ["turn_control"]
    assert turn_control_params["supported_metadata"] == []
    assert turn_control_params["provider_private_metadata"] == []
    steer_contract = turn_control_params["method_contracts"]["codex.turns.steer"]
    assert steer_contract["params"]["required"] == [
        "thread_id",
        "expected_turn_id",
        "request.parts",
    ]
    assert "metadata" in steer_contract["params"]["unsupported"]
    assert "metadata.codex.directory" in steer_contract["params"]["unsupported"]
    assert "metadata.codex.execution" in steer_contract["params"]["unsupported"]
    assert steer_contract["result"]["fields"] == ["ok", "thread_id", "turn_id"]
    assert any("active regular turn" in note for note in turn_control_params["consumer_guidance"])

    review_control = ext_by_uri[REVIEW_CONTROL_EXTENSION_URI]
    review_control_params = _require_params(review_control)
    assert review_control_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert review_control_params["profile"] == profile
    assert review_control_params["methods"]["start"] == "codex.review.start"
    assert review_control_params["methods"]["watch"] == "codex.review.watch"
    assert review_control_params["supported_metadata"] == []
    assert review_control_params["provider_private_metadata"] == []
    assert review_control_params["target_contracts"]["uncommittedChanges"] == {
        "required_fields": ["type"]
    }
    assert review_control_params["target_contracts"]["baseBranch"] == {
        "required_fields": ["type", "branch"]
    }
    assert review_control_params["target_contracts"]["commit"] == {
        "required_fields": ["type", "sha"],
        "optional_fields": ["title"],
    }
    assert review_control_params["target_contracts"]["custom"] == {
        "required_fields": ["type", "instructions"]
    }
    assert review_control_params["delivery_values"] == ["inline", "detached"]
    review_contract = review_control_params["method_contracts"]["codex.review.start"]
    assert review_contract["params"]["required"] == ["thread_id", "target.type"]
    assert "delivery" in review_contract["params"]["optional"]
    assert "metadata.codex.directory" in review_contract["params"]["unsupported"]
    assert review_contract["result"]["fields"] == ["ok", "turn_id", "review_thread_id"]
    watch_contract = review_control_params["method_contracts"]["codex.review.watch"]
    assert watch_contract["params"]["required"] == [
        "thread_id",
        "review_thread_id",
        "turn_id",
    ]
    assert watch_contract["params"]["optional"] == ["request.events"]
    assert watch_contract["result"]["fields"] == ["ok", "task_id", "context_id"]
    assert review_control_params["task_streaming"]["task_stream_method"] == "SubscribeToTask"
    assert review_control_params["task_streaming"]["watch_method"] == "codex.review.watch"
    assert review_control_params["task_streaming"]["supported_events"] == [
        "review.started",
        "review.status.changed",
        "review.completed",
        "review.failed",
    ]
    assert any("codex.review.watch" in note for note in review_control_params["consumer_guidance"])

    interrupt = ext_by_uri[INTERRUPT_CALLBACK_EXTENSION_URI]
    interrupt_params = _require_params(interrupt)
    assert interrupt_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert interrupt_params["profile"] == profile
    assert interrupt_params["request_id_field"] == "metadata.shared.interrupt.request_id"
    assert interrupt_params["supported_metadata"] == ["codex.directory"]
    assert interrupt_params["provider_private_metadata"] == ["codex.directory"]
    assert interrupt_params["methods"]["reply_permissions"] == "a2a.interrupt.permissions.reply"
    assert interrupt_params["methods"]["reply_elicitation"] == "a2a.interrupt.elicitation.reply"
    assert "permissions.asked" in interrupt_params["supported_interrupt_events"]
    assert "elicitation.asked" in interrupt_params["supported_interrupt_events"]
    assert interrupt_params["permissions_reply_contract"]["scope"] == (
        "optional persistence scope: turn or session"
    )
    assert interrupt_params["elicitation_reply_contract"]["action"] == (
        "accept, decline, or cancel"
    )
    assert interrupt_params["errors"]["business_codes"]["INTERRUPT_REQUEST_EXPIRED"] == -32007
    assert interrupt_params["errors"]["business_codes"]["INTERRUPT_TYPE_MISMATCH"] == -32008
    assert "expected_interrupt_type" in interrupt_params["errors"]["error_data_fields"]
    assert "actual_interrupt_type" in interrupt_params["errors"]["error_data_fields"]

    exec_control = ext_by_uri[EXEC_CONTROL_EXTENSION_URI]
    exec_control_params = _require_params(exec_control)
    assert exec_control_params["jsonrpc_endpoint"]["url_path"] == EXTENSION_JSONRPC_PATH
    assert exec_control_params["profile"] == profile
    assert exec_control_params["supported_metadata"] == ["codex.directory"]
    assert exec_control_params["provider_private_metadata"] == ["codex.directory"]
    assert exec_control_params["task_streaming"]["task_stream_method"] == "SubscribeToTask"
    assert exec_control_params["errors"]["business_codes"]["EXEC_FORBIDDEN"] == -32018
    start_contract = exec_control_params["method_contracts"]["codex.exec.start"]
    assert start_contract["execution_binding"] == "standalone_interactive_command_exec"
    assert start_contract["result"]["fields"] == ["ok", "task_id", "context_id", "process_id"]
    assert any("interactive command/exec session" in note for note in start_contract["notes"])

    wire_contract = ext_by_uri[WIRE_CONTRACT_EXTENSION_URI]
    wire_contract_params = _require_params(wire_contract)
    assert wire_contract_params["protocol_version"] == "1.0.0"
    assert wire_contract_params["default_protocol_version"] == "1.0"
    assert wire_contract_params["supported_protocol_versions"] == ["1.0"]
    assert set(wire_contract_params["protocol_compatibility"]["versions"]) == {"1.0"}
    assert (
        wire_contract_params["protocol_compatibility"]["versions"]["1.0"]["status"] == "supported"
    )
    assert (
        "A2A-Version"
        in wire_contract_params["protocol_compatibility"]["versions"]["1.0"]["supported_features"][
            0
        ]
    )
    assert "GetExtendedAgentCard" in wire_contract_params["all_jsonrpc_methods"]
    assert "CreateTaskPushNotificationConfig" in wire_contract_params["all_jsonrpc_methods"]
    assert (
        f"POST {REST_API_PATH_PREFIX}/message:send"
        in wire_contract_params["core"]["http_endpoints"]
    )
    assert (
        f"GET {REST_API_PATH_PREFIX}/extendedAgentCard"
        in wire_contract_params["core"]["http_endpoints"]
    )
    assert wire_contract_params["core"]["jsonrpc_endpoint"] == {
        "protocol_binding": "JSON-RPC",
        "protocol_version": "1.0.0",
        "url_path": CORE_JSONRPC_PATH,
    }
    assert wire_contract_params["extensions"]["jsonrpc_endpoint"] == {
        "protocol_binding": "JSON-RPC",
        "protocol_version": "1.0.0",
        "url_path": EXTENSION_JSONRPC_PATH,
    }
    assert wire_contract_params["transport_interfaces"] == [
        {
            "protocol_binding": "HTTP+JSON",
            "protocol_version": "1.0.0",
            "url_path_prefix": REST_API_PATH_PREFIX,
        },
        {
            "protocol_binding": "JSON-RPC",
            "protocol_version": "1.0.0",
            "url_path": CORE_JSONRPC_PATH,
        },
    ]

    compatibility = ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI]
    compatibility_params = _require_params(compatibility)
    assert compatibility_params["profile_id"] == "codex-a2a-single-tenant-coding-v1"
    assert compatibility_params["protocol_version"] == "1.0.0"
    assert compatibility_params["default_protocol_version"] == "1.0"
    assert compatibility_params["supported_protocol_versions"] == ["1.0"]
    assert (
        compatibility_params["protocol_compatibility"]
        == wire_contract_params["protocol_compatibility"]
    )
    assert compatibility_params["deployment"] == profile["deployment"]
    assert compatibility_params["runtime_features"] == profile["runtime_features"]
    assert compatibility_params["core"]["jsonrpc_endpoint"] == CORE_JSONRPC_PATH
    assert compatibility_params["extension_transport"]["jsonrpc_endpoint"] == EXTENSION_JSONRPC_PATH
    assert "GetExtendedAgentCard" in compatibility_params["core"]["jsonrpc_methods"]
    assert compatibility_params["extension_taxonomy"]["provider_private_metadata"] == [
        "codex.directory",
        "codex.execution",
    ]
    assert compatibility_params["method_retention"]["GetExtendedAgentCard"] == {
        "surface": "core",
        "availability": "always",
        "retention": "required",
    }
    assert compatibility_params["method_retention"]["CreateTaskPushNotificationConfig"] == {
        "surface": "core",
        "availability": "always",
        "retention": "required",
    }
    assert any(
        "single-tenant, shared-workspace coding profile" in note
        for note in compatibility_params["consumer_guidance"]
    )
    assert any("urn:a2a:*" in note for note in compatibility_params["consumer_guidance"])
    assert any(
        "execution_environment" in note for note in compatibility_params["consumer_guidance"]
    )
    assert any(
        "terminal SubscribeToTask replay-once behavior" in note
        for note in compatibility_params["consumer_guidance"]
    )
    assert any(
        "codex.interrupts.list" in note for note in compatibility_params["consumer_guidance"]
    )
    assert any("codex.threads.*" in note for note in compatibility_params["consumer_guidance"])
    assert any("codex.turns.*" in note for note in compatibility_params["consumer_guidance"])
    assert any("codex.review.*" in note for note in compatibility_params["consumer_guidance"])
    assert any("codex.exec.*" in note for note in compatibility_params["consumer_guidance"])
    assert any(
        "protocol_compatibility" in note for note in compatibility_params["consumer_guidance"]
    )
    interrupt_recovery_policy = compatibility_params["method_retention"]["codex.interrupts.list"]
    assert interrupt_recovery_policy["availability"] == "always"
    assert interrupt_recovery_policy["retention"] == "stable"
    assert interrupt_recovery_policy["extension_uri"] == "urn:codex-a2a:codex-interrupt-recovery/v1"
    assert compatibility_params["method_retention"]["codex.sessions.list"] == {
        "surface": "extension",
        "availability": "always",
        "retention": "stable",
        "extension_uri": "urn:codex-a2a:codex-session-query/v1",
    }
    exec_policy = compatibility_params["method_retention"]["codex.exec.start"]
    assert exec_policy["availability"] == "enabled"
    assert exec_policy["retention"] == "deployment-conditional"
    assert exec_policy["extension_uri"] == "urn:codex-a2a:codex-exec/v1"
    assert exec_policy["toggle"] == "A2A_ENABLE_EXEC_CONTROL"
    thread_policy = compatibility_params["method_retention"]["codex.threads.watch"]
    assert thread_policy["availability"] == "always"
    assert thread_policy["retention"] == "stable"
    assert thread_policy["extension_uri"] == "urn:codex-a2a:codex-thread-lifecycle/v1"
    turn_policy = compatibility_params["method_retention"]["codex.turns.steer"]
    assert turn_policy["availability"] == "enabled"
    assert turn_policy["retention"] == "deployment-conditional"
    assert turn_policy["extension_uri"] == "urn:codex-a2a:codex-turn-control/v1"
    assert turn_policy["toggle"] == "A2A_ENABLE_TURN_CONTROL"
    review_policy = compatibility_params["method_retention"]["codex.review.start"]
    assert review_policy["availability"] == "enabled"
    assert review_policy["retention"] == "deployment-conditional"
    assert review_policy["extension_uri"] == "urn:codex-a2a:codex-review/v1"
    assert review_policy["toggle"] == "A2A_ENABLE_REVIEW_CONTROL"
    review_watch_policy = compatibility_params["method_retention"]["codex.review.watch"]
    assert review_watch_policy["availability"] == "enabled"
    assert review_watch_policy["retention"] == "deployment-conditional"
    assert review_watch_policy["extension_uri"] == "urn:codex-a2a:codex-review/v1"
    assert review_watch_policy["toggle"] == "A2A_ENABLE_REVIEW_CONTROL"


def test_authenticated_extended_agent_card_chat_examples_include_project_hint_when_configured() -> (
    None
):
    card = build_authenticated_extended_agent_card(
        make_settings(a2a_bearer_token="test-token", a2a_project="alpha")
    )
    chat_skill = next(skill for skill in card.skills if skill.id == "codex.chat")
    assert any("project alpha" in example for example in _require_examples(chat_skill))


def test_public_agent_card_skills_are_minimal() -> None:
    card = build_agent_card(make_settings(a2a_bearer_token="test-token"))
    session_skill = next(skill for skill in card.skills if skill.id == "codex.sessions.query")
    thread_control_skill = next(
        skill for skill in card.skills if skill.id == "codex.threads.control"
    )
    thread_watch_skill = next(skill for skill in card.skills if skill.id == "codex.threads.watch")
    interrupt_recovery_skill = next(
        skill for skill in card.skills if skill.id == "codex.interrupt.recovery"
    )
    turn_control_skill = next(skill for skill in card.skills if skill.id == "codex.turns.control")
    review_control_skill = next(
        skill for skill in card.skills if skill.id == "codex.review.control"
    )
    review_watch_skill = next(skill for skill in card.skills if skill.id == "codex.review.watch")

    assert list(session_skill.examples) == []
    assert "provider-private" in session_skill.tags
    assert list(thread_control_skill.examples) == []
    assert "provider-private" in thread_control_skill.tags
    assert list(thread_watch_skill.examples) == []
    assert "provider-private" in thread_watch_skill.tags
    assert list(interrupt_recovery_skill.examples) == []
    assert "provider-private" in interrupt_recovery_skill.tags
    assert list(turn_control_skill.examples) == []
    assert "provider-private" in turn_control_skill.tags
    assert list(review_control_skill.examples) == []
    assert "provider-private" in review_control_skill.tags
    assert list(review_watch_skill.examples) == []
    assert "provider-private" in review_watch_skill.tags


def test_authenticated_extended_agent_card_omits_removed_session_control_contracts() -> None:
    card = build_authenticated_extended_agent_card(
        make_settings(
            a2a_bearer_token="test-token",
            a2a_interrupt_request_ttl_seconds=45,
        )
    )
    ext_by_uri = {ext.uri: ext for ext in card.capabilities.extensions or []}
    session_query = ext_by_uri[SESSION_QUERY_EXTENSION_URI]
    session_query_params = _require_params(session_query)

    assert "control_methods" not in session_query_params
    assert "codex.sessions.shell" not in session_query_params["method_contracts"]
    assert "codex.sessions.prompt_async" not in session_query_params["method_contracts"]
    assert "codex.sessions.command" not in session_query_params["method_contracts"]
    assert session_query_params["profile"]["runtime_features"]["interrupts"] == {
        "request_ttl_seconds": 45
    }
    assert session_query_params["profile"]["runtime_features"]["execution_environment"] == {
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
    wire_contract_params = _require_params(wire_contract)
    assert "codex.sessions.shell" not in wire_contract_params["all_jsonrpc_methods"]
    assert "codex.sessions.prompt_async" not in wire_contract_params["all_jsonrpc_methods"]
    assert "codex.sessions.command" not in wire_contract_params["all_jsonrpc_methods"]
    assert (
        "codex.sessions.shell"
        not in wire_contract_params["extensions"]["conditionally_available_methods"]
    )
    compatibility = ext_by_uri[COMPATIBILITY_PROFILE_EXTENSION_URI]
    compatibility_params = _require_params(compatibility)
    assert "codex.sessions.shell" not in compatibility_params["method_retention"]
    assert "session_shell" not in compatibility_params["runtime_features"]


def test_agent_card_hides_boundary_sensitive_control_surfaces_when_disabled() -> None:
    settings = make_settings(
        a2a_bearer_token="test-token",
        a2a_enable_turn_control=False,
        a2a_enable_review_control=False,
        a2a_enable_exec_control=False,
    )
    public_card = build_agent_card(settings)
    extended_card = build_authenticated_extended_agent_card(settings)

    public_skill_ids = {skill.id for skill in public_card.skills or []}
    extended_skill_ids = {skill.id for skill in extended_card.skills or []}
    for skill_id in (
        "codex.turns.control",
        "codex.review.control",
        "codex.review.watch",
        "codex.exec.control",
        "codex.exec.stream",
    ):
        assert skill_id not in public_skill_ids
        assert skill_id not in extended_skill_ids

    ext_by_uri = {ext.uri: ext for ext in extended_card.capabilities.extensions or []}
    turn_params = _require_params(ext_by_uri[TURN_CONTROL_EXTENSION_URI])
    review_params = _require_params(ext_by_uri[REVIEW_CONTROL_EXTENSION_URI])
    exec_params = _require_params(ext_by_uri[EXEC_CONTROL_EXTENSION_URI])
    wire_contract_params = _require_params(ext_by_uri[WIRE_CONTRACT_EXTENSION_URI])

    assert turn_params["methods"] == {}
    assert turn_params["method_contracts"] == {}
    assert turn_params["availability"] == "disabled"
    assert turn_params["toggle"] == "A2A_ENABLE_TURN_CONTROL"
    assert review_params["methods"] == {}
    assert review_params["method_contracts"] == {}
    assert review_params["availability"] == "disabled"
    assert review_params["toggle"] == "A2A_ENABLE_REVIEW_CONTROL"
    assert exec_params["methods"] == {}
    assert exec_params["method_contracts"] == {}
    assert exec_params["availability"] == "disabled"
    assert exec_params["toggle"] == "A2A_ENABLE_EXEC_CONTROL"
    assert "codex.turns.steer" not in wire_contract_params["all_jsonrpc_methods"]
    assert "codex.review.start" not in wire_contract_params["all_jsonrpc_methods"]
    assert "codex.review.watch" not in wire_contract_params["all_jsonrpc_methods"]
    assert "codex.exec.start" not in wire_contract_params["all_jsonrpc_methods"]
    assert wire_contract_params["extensions"]["conditionally_available_methods"] == {
        "codex.turns.steer": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_TURN_CONTROL",
        },
        "codex.review.start": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_REVIEW_CONTROL",
        },
        "codex.review.watch": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_REVIEW_CONTROL",
        },
        "codex.exec.start": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_EXEC_CONTROL",
        },
        "codex.exec.write": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_EXEC_CONTROL",
        },
        "codex.exec.resize": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_EXEC_CONTROL",
        },
        "codex.exec.terminate": {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_EXEC_CONTROL",
        },
    }
