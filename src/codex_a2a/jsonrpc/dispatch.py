from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from codex_a2a.contracts import extension_specs
from codex_a2a.contracts.extension_registry import build_method_extension_uri_by_method


@dataclass(frozen=True)
class ExtensionMethodRegistry:
    session_query_methods: frozenset[str]
    discovery_query_methods: frozenset[str]
    discovery_control_methods: frozenset[str]
    thread_lifecycle_control_methods: frozenset[str]
    interrupt_recovery_methods: frozenset[str]
    turn_control_methods: frozenset[str]
    review_control_methods: frozenset[str]
    exec_control_methods: frozenset[str]
    interrupt_callback_methods: frozenset[str]
    extension_methods: frozenset[str]
    extension_uri_by_method: Mapping[str, str]

    @classmethod
    def from_methods(cls, methods: dict[str, str]) -> ExtensionMethodRegistry:
        configured_methods = tuple(methods.values())
        duplicates = sorted(
            method for method, count in Counter(configured_methods).items() if count > 1
        )
        if duplicates:
            raise ValueError(f"Extension methods configured under multiple keys: {duplicates}")

        extension_uri_by_method = build_method_extension_uri_by_method(
            enabled_methods=configured_methods
        )

        def methods_for(extension_uri: str) -> frozenset[str]:
            return frozenset(
                method
                for method, declared_uri in extension_uri_by_method.items()
                if declared_uri == extension_uri
            )

        session_query_methods = methods_for(extension_specs.SESSION_QUERY_EXTENSION_URI)
        discovery_methods = methods_for(extension_specs.DISCOVERY_EXTENSION_URI)
        discovery_control_methods = frozenset({methods["watch"]})
        if not discovery_control_methods.issubset(discovery_methods):
            raise ValueError("Discovery watch method must belong to the discovery extension")
        discovery_query_methods = discovery_methods - discovery_control_methods
        thread_lifecycle_control_methods = methods_for(
            extension_specs.THREAD_LIFECYCLE_EXTENSION_URI
        )
        interrupt_recovery_methods = methods_for(extension_specs.INTERRUPT_RECOVERY_EXTENSION_URI)
        turn_control_methods = methods_for(extension_specs.TURN_CONTROL_EXTENSION_URI)
        review_control_methods = methods_for(extension_specs.REVIEW_CONTROL_EXTENSION_URI)
        exec_control_methods = methods_for(extension_specs.EXEC_CONTROL_EXTENSION_URI)
        interrupt_callback_methods = methods_for(extension_specs.INTERRUPT_CALLBACK_EXTENSION_URI)
        extension_methods = frozenset(extension_uri_by_method)
        return cls(
            session_query_methods=session_query_methods,
            discovery_query_methods=discovery_query_methods,
            discovery_control_methods=discovery_control_methods,
            thread_lifecycle_control_methods=thread_lifecycle_control_methods,
            interrupt_recovery_methods=interrupt_recovery_methods,
            turn_control_methods=turn_control_methods,
            review_control_methods=review_control_methods,
            exec_control_methods=exec_control_methods,
            interrupt_callback_methods=interrupt_callback_methods,
            extension_methods=extension_methods,
            extension_uri_by_method=extension_uri_by_method,
        )

    def is_extension_method(self, method: str) -> bool:
        return method in self.extension_methods

    def extension_uri_for_method(self, method: str) -> str | None:
        return self.extension_uri_by_method.get(method)
