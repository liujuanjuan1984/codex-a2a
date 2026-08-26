from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from codex_a2a.contracts import extension_specs


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
        turn_method = methods.get("turn_steer")
        review_start_method = methods.get("review_start")
        review_watch_method = methods.get("review_watch")
        exec_start_method = methods.get("exec_start")
        exec_write_method = methods.get("exec_write")
        exec_resize_method = methods.get("exec_resize")
        exec_terminate_method = methods.get("exec_terminate")
        interrupt_list_method = methods.get("interrupts_list")
        discovery_plugin_list_method = methods.get("list_plugins")
        discovery_plugin_read_method = methods.get("read_plugin")
        session_query_methods = frozenset(
            {
                methods["list_sessions"],
                methods["get_session_messages"],
            }
        )
        discovery_query_methods = frozenset(
            method
            for method in (
                methods["list_skills"],
                methods["list_apps"],
                discovery_plugin_list_method,
                discovery_plugin_read_method,
            )
            if method is not None
        )
        discovery_control_methods = frozenset({methods["watch"]})
        thread_lifecycle_control_methods = frozenset(
            {
                methods["thread_fork"],
                methods["thread_archive"],
                methods["thread_unarchive"],
                methods["thread_metadata_update"],
                methods["thread_watch"],
                methods["thread_watch_release"],
            }
        )
        interrupt_recovery_methods = frozenset(
            method for method in (interrupt_list_method,) if method is not None
        )
        turn_control_methods = frozenset(method for method in (turn_method,) if method is not None)
        review_control_methods = frozenset(
            method for method in (review_start_method, review_watch_method) if method is not None
        )
        exec_control_methods = frozenset(
            method
            for method in (
                exec_start_method,
                exec_write_method,
                exec_resize_method,
                exec_terminate_method,
            )
            if method is not None
        )
        interrupt_callback_methods = frozenset(
            {
                methods["reply_permission"],
                methods["reply_question"],
                methods["reject_question"],
                methods["reply_permissions"],
                methods["reply_elicitation"],
            }
        )
        extension_methods = (
            session_query_methods
            | discovery_query_methods
            | discovery_control_methods
            | thread_lifecycle_control_methods
            | interrupt_recovery_methods
            | turn_control_methods
            | review_control_methods
            | exec_control_methods
            | interrupt_callback_methods
        )
        method_groups = (
            (session_query_methods, extension_specs.SESSION_QUERY_EXTENSION_URI),
            (
                discovery_query_methods | discovery_control_methods,
                extension_specs.DISCOVERY_EXTENSION_URI,
            ),
            (thread_lifecycle_control_methods, extension_specs.THREAD_LIFECYCLE_EXTENSION_URI),
            (interrupt_recovery_methods, extension_specs.INTERRUPT_RECOVERY_EXTENSION_URI),
            (turn_control_methods, extension_specs.TURN_CONTROL_EXTENSION_URI),
            (review_control_methods, extension_specs.REVIEW_CONTROL_EXTENSION_URI),
            (exec_control_methods, extension_specs.EXEC_CONTROL_EXTENSION_URI),
            (interrupt_callback_methods, extension_specs.INTERRUPT_CALLBACK_EXTENSION_URI),
        )
        extension_uri_by_method: dict[str, str] = {}
        for method_group, extension_uri in method_groups:
            for method in method_group:
                if method in extension_uri_by_method:
                    raise ValueError(f"Extension method maps to multiple extension URIs: {method}")
                extension_uri_by_method[method] = extension_uri
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
            extension_uri_by_method=MappingProxyType(extension_uri_by_method),
        )

    def is_extension_method(self, method: str) -> bool:
        return method in self.extension_methods

    def extension_uri_for_method(self, method: str) -> str | None:
        return self.extension_uri_by_method.get(method)
