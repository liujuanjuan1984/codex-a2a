from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionMethodRegistry:
    session_query_methods: frozenset[str]
    session_control_methods: frozenset[str]
    discovery_query_methods: frozenset[str]
    discovery_control_methods: frozenset[str]
    thread_lifecycle_control_methods: frozenset[str]
    turn_control_methods: frozenset[str]
    review_control_methods: frozenset[str]
    exec_control_methods: frozenset[str]
    interrupt_callback_methods: frozenset[str]
    extension_methods: frozenset[str]

    @classmethod
    def from_methods(cls, methods: dict[str, str]) -> ExtensionMethodRegistry:
        shell_method = methods.get("shell")
        turn_method = methods.get("turn_steer")
        review_start_method = methods.get("review_start")
        review_watch_method = methods.get("review_watch")
        exec_start_method = methods.get("exec_start")
        exec_write_method = methods.get("exec_write")
        exec_resize_method = methods.get("exec_resize")
        exec_terminate_method = methods.get("exec_terminate")
        session_query_methods = frozenset(
            {
                methods["list_sessions"],
                methods["get_session_messages"],
            }
        )
        session_control = {
            methods["prompt_async"],
            methods["command"],
        }
        if shell_method is not None:
            session_control.add(shell_method)
        session_control_methods = frozenset(session_control)
        discovery_query_methods = frozenset(
            {
                methods["list_skills"],
                methods["list_apps"],
                methods["list_plugins"],
                methods["read_plugin"],
            }
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
            | session_control_methods
            | discovery_query_methods
            | discovery_control_methods
            | thread_lifecycle_control_methods
            | turn_control_methods
            | review_control_methods
            | exec_control_methods
            | interrupt_callback_methods
        )
        return cls(
            session_query_methods=session_query_methods,
            session_control_methods=session_control_methods,
            discovery_query_methods=discovery_query_methods,
            discovery_control_methods=discovery_control_methods,
            thread_lifecycle_control_methods=thread_lifecycle_control_methods,
            turn_control_methods=turn_control_methods,
            review_control_methods=review_control_methods,
            exec_control_methods=exec_control_methods,
            interrupt_callback_methods=interrupt_callback_methods,
            extension_methods=extension_methods,
        )

    def is_extension_method(self, method: str) -> bool:
        return method in self.extension_methods
