from __future__ import annotations

from a2a.types import AgentExtension

from codex_a2a.contracts.extension_registry import build_agent_card_extensions_from_registry
from codex_a2a.profile.runtime import RuntimeProfile


def build_agent_extensions(
    *,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentExtension]:
    return build_agent_card_extensions_from_registry(
        runtime_profile=runtime_profile,
        include_detailed_contracts=include_detailed_contracts,
    )
