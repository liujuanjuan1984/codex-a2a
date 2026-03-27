from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtensionMethodRegistry:
    session_query_methods: frozenset[str]
    session_control_methods: frozenset[str]
    exec_control_methods: frozenset[str]
    interrupt_callback_methods: frozenset[str]
    extension_methods: frozenset[str]

    @classmethod
    def from_methods(cls, methods: dict[str, str]) -> ExtensionMethodRegistry:
        shell_method = methods.get("shell")
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
        exec_control_methods = frozenset(
            {
                methods["exec_start"],
                methods["exec_write"],
                methods["exec_resize"],
                methods["exec_terminate"],
            }
        )
        interrupt_callback_methods = frozenset(
            {
                methods["reply_permission"],
                methods["reply_question"],
                methods["reject_question"],
            }
        )
        extension_methods = (
            session_query_methods
            | session_control_methods
            | exec_control_methods
            | interrupt_callback_methods
        )
        return cls(
            session_query_methods=session_query_methods,
            session_control_methods=session_control_methods,
            exec_control_methods=exec_control_methods,
            interrupt_callback_methods=interrupt_callback_methods,
            extension_methods=extension_methods,
        )

    def is_extension_method(self, method: str) -> bool:
        return method in self.extension_methods
