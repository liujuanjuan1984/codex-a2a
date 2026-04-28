from __future__ import annotations

from typing import Any

from a2a.types import AgentExtension

from codex_a2a.contracts.extensions import (
    SESSION_BINDING_EXTENSION_URI,
    STREAMING_EXTENSION_URI,
    build_session_binding_extension_params,
    build_streaming_extension_params,
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
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentExtension]:
    session_binding_extension_params = build_session_binding_extension_params(
        runtime_profile=runtime_profile,
    )
    streaming_extension_params = build_streaming_extension_params()

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
    ]
