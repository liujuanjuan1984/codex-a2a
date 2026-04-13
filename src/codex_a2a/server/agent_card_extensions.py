from __future__ import annotations

from typing import Any

from a2a.types import AgentExtension

from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import (
    COMPATIBILITY_PROFILE_EXTENSION_URI,
    DISCOVERY_EXTENSION_URI,
    EXEC_CONTROL_EXTENSION_URI,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    INTERRUPT_RECOVERY_EXTENSION_URI,
    REVIEW_CONTROL_EXTENSION_URI,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_EXTENSION_URI,
    STREAMING_EXTENSION_URI,
    THREAD_LIFECYCLE_EXTENSION_URI,
    TURN_CONTROL_EXTENSION_URI,
    WIRE_CONTRACT_EXTENSION_URI,
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
from codex_a2a.profile.runtime import RuntimeProfile


def _select_public_extension_params(
    params: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: params[key] for key in keys if key in params}


def _build_public_streaming_extension_params(
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_metadata_field": params["artifact_metadata_field"],
        "status_metadata_field": params["status_metadata_field"],
        "interrupt_metadata_field": params["interrupt_metadata_field"],
        "session_metadata_field": params["session_metadata_field"],
        "usage_metadata_field": params["usage_metadata_field"],
        "block_types": params["block_types"],
        "block_part_types": params["block_part_types"],
        "stream_fields": _select_public_extension_params(
            params["stream_fields"],
            keys=("block_type", "message_id", "sequence", "source"),
        ),
        "status_stream_fields": _select_public_extension_params(
            params["status_stream_fields"],
            keys=("type", "status", "source", "event_id"),
        ),
        "session_fields": _select_public_extension_params(
            params["session_fields"],
            keys=("id", "title"),
        ),
        "interrupt_fields": _select_public_extension_params(
            params["interrupt_fields"],
            keys=("request_id", "type", "phase", "resolution"),
        ),
        "usage_fields": _select_public_extension_params(
            params["usage_fields"],
            keys=("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"),
        ),
    }


def build_agent_extensions(
    *,
    settings: Settings,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentExtension]:
    session_binding_extension_params = build_session_binding_extension_params(
        runtime_profile=runtime_profile,
    )
    streaming_extension_params = build_streaming_extension_params()
    session_query_extension_params = build_session_query_extension_params(
        runtime_profile=runtime_profile,
    )
    discovery_extension_params = build_discovery_extension_params(
        runtime_profile=runtime_profile,
    )
    thread_lifecycle_extension_params = build_thread_lifecycle_extension_params(
        runtime_profile=runtime_profile,
    )
    turn_control_extension_params = build_turn_control_extension_params(
        runtime_profile=runtime_profile,
    )
    review_control_extension_params = build_review_control_extension_params(
        runtime_profile=runtime_profile,
    )
    exec_control_extension_params = build_exec_control_extension_params(
        runtime_profile=runtime_profile,
    )
    interrupt_callback_extension_params = build_interrupt_callback_extension_params(
        runtime_profile=runtime_profile,
    )
    interrupt_recovery_extension_params = build_interrupt_recovery_extension_params(
        runtime_profile=runtime_profile,
    )
    wire_contract_extension_params = build_wire_contract_extension_params(
        protocol_version=settings.a2a_protocol_version,
        supported_protocol_versions=settings.a2a_supported_protocol_versions,
        default_protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )
    compatibility_profile_params = build_compatibility_profile_params(
        protocol_version=settings.a2a_protocol_version,
        supported_protocol_versions=settings.a2a_supported_protocol_versions,
        default_protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )

    return [
        AgentExtension(
            uri=SESSION_BINDING_EXTENSION_URI,
            required=False,
            description=(
                "Shared contract to bind A2A messages to an existing Codex session "
                "when continuing a previous chat. Clients should pass "
                "metadata.shared.session.id. The metadata.codex.directory and "
                "metadata.codex.execution fields remain available as Codex-private "
                "request overrides under server-side validation."
            ),
            params=(
                session_binding_extension_params
                if include_detailed_contracts
                else _select_public_extension_params(
                    session_binding_extension_params,
                    keys=(
                        "metadata_field",
                        "behavior",
                        "supported_metadata",
                        "provider_private_metadata",
                    ),
                )
            ),
        ),
        AgentExtension(
            uri=STREAMING_EXTENSION_URI,
            required=False,
            description=(
                "Shared streaming metadata contract for canonical block hints, "
                "timeline identity, usage, and interactive interrupt metadata."
            ),
            params=(
                streaming_extension_params
                if include_detailed_contracts
                else _build_public_streaming_extension_params(streaming_extension_params)
            ),
        ),
        AgentExtension(
            uri=SESSION_QUERY_EXTENSION_URI,
            required=False,
            description=(
                "Support Codex session list/history queries via custom JSON-RPC methods "
                "on the agent's A2A JSON-RPC interface, including structured rich "
                "input for codex.sessions.prompt_async."
            ),
            params=session_query_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=DISCOVERY_EXTENSION_URI,
            required=False,
            description=(
                "Expose read-only skills/apps/plugins discovery plus a task-stream "
                "notification bridge for invalidation and refresh signals."
            ),
            params=discovery_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=THREAD_LIFECYCLE_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private thread lifecycle control plus a task-stream "
                "notification bridge for lifecycle status, archive, and restore "
                "signals."
            ),
            params=thread_lifecycle_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=TURN_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private active-turn steering through the custom "
                "JSON-RPC method codex.turns.steer."
            ),
            params=turn_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=REVIEW_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private reviewer control plus a task-stream "
                "watch bridge through the custom JSON-RPC methods "
                "codex.review.start and codex.review.watch."
            ),
            params=review_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=EXEC_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose standalone interactive command execution via custom JSON-RPC "
                "methods codex.exec.start, codex.exec.write, codex.exec.resize, and "
                "codex.exec.terminate."
            ),
            params=exec_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=INTERRUPT_RECOVERY_EXTENSION_URI,
            required=False,
            description=(
                "Expose adapter-local interrupt recovery so authenticated clients can "
                "rediscover pending interrupt request_ids after reconnecting."
            ),
            params=(
                interrupt_recovery_extension_params
                if include_detailed_contracts
                else _select_public_extension_params(
                    interrupt_recovery_extension_params,
                    keys=("methods", "supported_interrupt_types", "identity_scope"),
                )
            ),
        ),
        AgentExtension(
            uri=INTERRUPT_CALLBACK_EXTENSION_URI,
            required=False,
            description=(
                "Handle interactive interrupt callbacks generated during "
                "streaming through shared JSON-RPC methods."
            ),
            params=(
                interrupt_callback_extension_params
                if include_detailed_contracts
                else _select_public_extension_params(
                    interrupt_callback_extension_params,
                    keys=("methods", "supported_interrupt_events", "request_id_field"),
                )
            ),
        ),
        AgentExtension(
            uri=COMPATIBILITY_PROFILE_EXTENSION_URI,
            required=False,
            description=(
                "Machine-readable compatibility profile for the current A2A core "
                "baseline, declared custom extensions, and retention policy."
            ),
            params=compatibility_profile_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=WIRE_CONTRACT_EXTENSION_URI,
            required=False,
            description=(
                "Declare the current JSON-RPC/HTTP method boundary and the "
                "unsupported method error contract for generic A2A clients."
            ),
            params=wire_contract_extension_params if include_detailed_contracts else None,
        ),
    ]
