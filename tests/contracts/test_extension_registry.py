from codex_a2a.contracts.extension_registry import (
    EXTENSION_CONTRACT_REGISTRY,
    build_agent_card_extensions_from_registry,
    build_extension_taxonomy_from_registry,
    build_openapi_extension_contracts_from_registry,
)
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
)
from codex_a2a.profile.runtime import build_runtime_profile
from tests.support.settings import make_settings


def test_extension_registry_captures_phase1_inventory() -> None:
    descriptors = EXTENSION_CONTRACT_REGISTRY

    assert [descriptor.key for descriptor in descriptors] == [
        "session_binding",
        "streaming",
        "session_query",
        "discovery",
        "thread_lifecycle",
        "interrupt_recovery",
        "turn_control",
        "review_control",
        "exec_control",
        "interrupt_callback",
        "wire_contract",
        "compatibility_profile",
    ]
    assert [descriptor.uri for descriptor in descriptors] == [
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
    ]
    public_keys = [descriptor.key for descriptor in descriptors if descriptor.public_agent_card]
    authenticated_keys = [
        descriptor.key for descriptor in descriptors if descriptor.authenticated_agent_card
    ]
    assert public_keys == ["session_binding", "streaming", "interrupt_callback"]
    assert authenticated_keys == [
        "session_binding",
        "streaming",
        "session_query",
        "discovery",
        "thread_lifecycle",
        "interrupt_recovery",
        "turn_control",
        "review_control",
        "exec_control",
        "interrupt_callback",
        "wire_contract",
        "compatibility_profile",
    ]
    negotiated_keys = [
        descriptor.key for descriptor in descriptors if descriptor.negotiation_mode == "negotiated"
    ]
    declaration_only_keys = [
        descriptor.key
        for descriptor in descriptors
        if descriptor.negotiation_mode == "declaration_only"
    ]
    not_applicable_keys = [
        descriptor.key
        for descriptor in descriptors
        if descriptor.negotiation_mode == "not_applicable"
    ]
    assert negotiated_keys == ["session_binding", "streaming"]
    assert declaration_only_keys == [
        "session_query",
        "discovery",
        "thread_lifecycle",
        "interrupt_recovery",
        "turn_control",
        "review_control",
        "exec_control",
        "interrupt_callback",
    ]
    assert not_applicable_keys == ["wire_contract", "compatibility_profile"]


def test_registry_builds_agent_card_extensions_for_current_phase1_surface() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)

    public_extensions = build_agent_card_extensions_from_registry(
        settings=settings,
        runtime_profile=runtime_profile,
        include_detailed_contracts=False,
    )
    authenticated_extensions = build_agent_card_extensions_from_registry(
        settings=settings,
        runtime_profile=runtime_profile,
        include_detailed_contracts=True,
    )

    assert [extension.uri for extension in public_extensions] == [
        SESSION_BINDING_EXTENSION_URI,
        STREAMING_EXTENSION_URI,
        INTERRUPT_CALLBACK_EXTENSION_URI,
    ]
    assert [extension.uri for extension in authenticated_extensions] == [
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
    ]


def test_registry_builds_openapi_contract_groups() -> None:
    settings = make_settings(a2a_bearer_token="test-token")
    runtime_profile = build_runtime_profile(settings)

    shared_contracts = build_openapi_extension_contracts_from_registry(
        settings=None,
        runtime_profile=runtime_profile,
        group="a2a",
    )
    codex_contracts = build_openapi_extension_contracts_from_registry(
        settings=settings,
        runtime_profile=runtime_profile,
        group="codex",
    )

    assert list(shared_contracts) == ["session_binding", "streaming", "interrupt_callback"]
    assert list(codex_contracts) == [
        "session_query",
        "discovery",
        "thread_lifecycle",
        "interrupt_recovery",
        "turn_control",
        "review_control",
        "exec_control",
        "wire_contract",
        "compatibility_profile",
    ]


def test_interrupt_callback_family_does_not_imply_anonymous_invocation() -> None:
    interrupt_descriptor = next(
        descriptor
        for descriptor in EXTENSION_CONTRACT_REGISTRY
        if descriptor.uri == INTERRUPT_CALLBACK_EXTENSION_URI
    )

    assert interrupt_descriptor.family == "shared"
    assert interrupt_descriptor.negotiation_mode == "declaration_only"
    assert interrupt_descriptor.public_agent_card is True
    assert interrupt_descriptor.authenticated_agent_card is True
    assert interrupt_descriptor.openapi_group == "a2a"
    assert interrupt_descriptor.public_params_keys == (
        "methods",
        "supported_interrupt_events",
        "interrupt_metadata_field",
        "request_id_field",
        "authorization",
    )


def test_extension_taxonomy_is_derived_from_registry() -> None:
    assert build_extension_taxonomy_from_registry() == {
        "shared_agent_card_extensions": [
            SESSION_BINDING_EXTENSION_URI,
            STREAMING_EXTENSION_URI,
            INTERRUPT_CALLBACK_EXTENSION_URI,
        ],
        "shared_provider_private_contracts": [],
        "codex_provider_private_contracts": [
            SESSION_QUERY_EXTENSION_URI,
            DISCOVERY_EXTENSION_URI,
            THREAD_LIFECYCLE_EXTENSION_URI,
            INTERRUPT_RECOVERY_EXTENSION_URI,
            TURN_CONTROL_EXTENSION_URI,
            REVIEW_CONTROL_EXTENSION_URI,
            EXEC_CONTROL_EXTENSION_URI,
            WIRE_CONTRACT_EXTENSION_URI,
            COMPATIBILITY_PROFILE_EXTENSION_URI,
        ],
    }
