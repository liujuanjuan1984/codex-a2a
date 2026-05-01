from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from a2a.types import AgentExtension

from codex_a2a.config import Settings
from codex_a2a.profile.runtime import RuntimeProfile

from .extension_specs import (
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
)


@dataclass(frozen=True)
class ExtensionContractDescriptor:
    key: str
    uri: str
    title: str
    description: str
    family: Literal["shared", "provider_private", "machine_readable"]
    # negotiated: request-level activation via A2A-Extensions is meaningful
    # declaration_only: discover through Agent Card/OpenAPI and invoke directly
    # not_applicable: descriptive metadata, not an activatable runtime extension
    negotiation_mode: Literal["negotiated", "declaration_only", "not_applicable"]
    public_agent_card: bool
    authenticated_agent_card: bool
    openapi_group: Literal["a2a", "codex"] | None
    taxonomy_group: (
        Literal[
            "shared_agent_card_extensions",
            "shared_provider_private_contracts",
            "codex_provider_private_contracts",
        ]
        | None
    )
    params_builder_name: str
    params_builder_signature: Literal["no_args", "runtime_profile", "protocol_version"]
    public_params_keys: tuple[str, ...] | None = None
    public_params_transform: Literal["streaming_public"] | None = None


def _select_public_extension_params(
    params: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: params[key] for key in keys if key in params}


def _build_public_streaming_extension_params(params: dict[str, Any]) -> dict[str, Any]:
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


def _build_extension_contract_params(
    descriptor: ExtensionContractDescriptor,
    settings: Settings | None,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    from . import extensions as contract_extensions

    builder = getattr(contract_extensions, descriptor.params_builder_name)
    if descriptor.params_builder_signature == "no_args":
        return dict(builder())
    if descriptor.params_builder_signature == "runtime_profile":
        return dict(builder(runtime_profile=runtime_profile))
    if settings is None:
        msg = f"settings are required to build {descriptor.key}"
        raise ValueError(msg)
    return dict(
        builder(
            protocol_version=settings.a2a_protocol_version,
            runtime_profile=runtime_profile,
        )
    )


def _build_agent_card_extension_params(
    descriptor: ExtensionContractDescriptor,
    *,
    settings: Settings,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> dict[str, Any]:
    params = _build_extension_contract_params(descriptor, settings, runtime_profile)
    if include_detailed_contracts:
        return params
    if descriptor.public_params_transform == "streaming_public":
        return _build_public_streaming_extension_params(params)
    if descriptor.public_params_keys is not None:
        return _select_public_extension_params(params, keys=descriptor.public_params_keys)
    return params


EXTENSION_CONTRACT_REGISTRY: tuple[ExtensionContractDescriptor, ...] = (
    ExtensionContractDescriptor(
        key="session_binding",
        uri=SESSION_BINDING_EXTENSION_URI,
        title="Shared Session Binding v1",
        description=(
            "Shared contract to bind A2A messages to an existing Codex session "
            "when continuing a previous chat. Clients should pass "
            "metadata.shared.session.id. The metadata.codex.directory and "
            "metadata.codex.execution fields remain available as Codex-private "
            "request overrides under server-side validation."
        ),
        family="shared",
        negotiation_mode="negotiated",
        public_agent_card=True,
        authenticated_agent_card=True,
        openapi_group="a2a",
        taxonomy_group="shared_agent_card_extensions",
        params_builder_name="build_session_binding_extension_params",
        params_builder_signature="runtime_profile",
        public_params_keys=(
            "metadata_field",
            "behavior",
            "supported_metadata",
            "provider_private_metadata",
        ),
    ),
    ExtensionContractDescriptor(
        key="streaming",
        uri=STREAMING_EXTENSION_URI,
        title="Shared Stream Hints v1",
        description=(
            "Shared streaming metadata contract for canonical block hints, "
            "timeline identity, usage, and interactive interrupt metadata."
        ),
        family="shared",
        negotiation_mode="negotiated",
        public_agent_card=True,
        authenticated_agent_card=True,
        openapi_group="a2a",
        taxonomy_group="shared_agent_card_extensions",
        params_builder_name="build_streaming_extension_params",
        params_builder_signature="no_args",
        public_params_transform="streaming_public",
    ),
    ExtensionContractDescriptor(
        key="session_query",
        uri=SESSION_QUERY_EXTENSION_URI,
        title="Codex Session Query v1",
        description="Provider-private Codex session history and low-risk control methods.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_session_query_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="discovery",
        uri=DISCOVERY_EXTENSION_URI,
        title="Codex Discovery v1",
        description="Provider-private skills, apps, plugins, and watch bridge methods.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_discovery_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="thread_lifecycle",
        uri=THREAD_LIFECYCLE_EXTENSION_URI,
        title="Codex Thread Lifecycle v1",
        description="Provider-private thread lifecycle control and watch bridge methods.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_thread_lifecycle_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="interrupt_recovery",
        uri=INTERRUPT_RECOVERY_EXTENSION_URI,
        title="Codex Interrupt Recovery v1",
        description="Provider-private interrupt rediscovery contract for authenticated callers.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_interrupt_recovery_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="turn_control",
        uri=TURN_CONTROL_EXTENSION_URI,
        title="Codex Turn Control v1",
        description="Provider-private active-turn steering for already-running regular turns.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_turn_control_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="review_control",
        uri=REVIEW_CONTROL_EXTENSION_URI,
        title="Codex Review Control v1",
        description="Provider-private review control and lifecycle watch bridge.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_review_control_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="exec_control",
        uri=EXEC_CONTROL_EXTENSION_URI,
        title="Codex Exec v1",
        description="Provider-private standalone interactive command execution.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_exec_control_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="interrupt_callback",
        uri=INTERRUPT_CALLBACK_EXTENSION_URI,
        title="Shared Interactive Interrupt v1",
        description="Shared repo-family interrupt callback reply methods.",
        family="provider_private",
        negotiation_mode="declaration_only",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="shared_provider_private_contracts",
        params_builder_name="build_interrupt_callback_extension_params",
        params_builder_signature="runtime_profile",
    ),
    ExtensionContractDescriptor(
        key="wire_contract",
        uri=WIRE_CONTRACT_EXTENSION_URI,
        title="A2A Wire Contract v1",
        description="Machine-readable wire-level contract metadata.",
        family="machine_readable",
        negotiation_mode="not_applicable",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_wire_contract_extension_params",
        params_builder_signature="protocol_version",
    ),
    ExtensionContractDescriptor(
        key="compatibility_profile",
        uri=COMPATIBILITY_PROFILE_EXTENSION_URI,
        title="A2A Compatibility Profile v1",
        description="Machine-readable compatibility profile metadata.",
        family="machine_readable",
        negotiation_mode="not_applicable",
        public_agent_card=False,
        authenticated_agent_card=True,
        openapi_group="codex",
        taxonomy_group="codex_provider_private_contracts",
        params_builder_name="build_compatibility_profile_params",
        params_builder_signature="protocol_version",
    ),
)


def build_agent_card_extensions_from_registry(
    *,
    settings: Settings,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentExtension]:
    extensions: list[AgentExtension] = []
    for descriptor in EXTENSION_CONTRACT_REGISTRY:
        include_on_surface = (
            descriptor.authenticated_agent_card
            if include_detailed_contracts
            else descriptor.public_agent_card
        )
        if not include_on_surface:
            continue
        extensions.append(
            AgentExtension(
                uri=descriptor.uri,
                required=False,
                description=descriptor.description,
                params=_build_agent_card_extension_params(
                    descriptor,
                    settings=settings,
                    runtime_profile=runtime_profile,
                    include_detailed_contracts=include_detailed_contracts,
                ),
            )
        )
    return extensions


def build_openapi_extension_contracts_from_registry(
    *,
    settings: Settings | None,
    runtime_profile: RuntimeProfile,
    group: Literal["a2a", "codex"],
) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for descriptor in EXTENSION_CONTRACT_REGISTRY:
        if descriptor.openapi_group != group:
            continue
        contracts[descriptor.key] = _build_extension_contract_params(
            descriptor,
            settings,
            runtime_profile,
        )
    return contracts


def build_extension_taxonomy_from_registry() -> dict[str, list[str]]:
    taxonomy: dict[str, list[str]] = {
        "shared_agent_card_extensions": [],
        "shared_provider_private_contracts": [],
        "codex_provider_private_contracts": [],
    }
    for descriptor in EXTENSION_CONTRACT_REGISTRY:
        if descriptor.taxonomy_group is None:
            continue
        taxonomy[descriptor.taxonomy_group].append(descriptor.uri)
    return taxonomy
