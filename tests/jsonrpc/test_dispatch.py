from codex_a2a.contracts.extensions import (
    INTERRUPT_CALLBACK_METHODS,
    SESSION_CONTROL_METHODS,
    SESSION_QUERY_METHODS,
)
from codex_a2a.jsonrpc.dispatch import ExtensionMethodRegistry


def test_extension_method_registry_partitions_methods() -> None:
    registry = ExtensionMethodRegistry.from_methods(
        {
            **SESSION_QUERY_METHODS,
            **SESSION_CONTROL_METHODS,
            **INTERRUPT_CALLBACK_METHODS,
        }
    )

    assert registry.session_query_methods == frozenset(
        {
            SESSION_QUERY_METHODS["list_sessions"],
            SESSION_QUERY_METHODS["get_session_messages"],
        }
    )
    assert registry.session_control_methods == frozenset(SESSION_CONTROL_METHODS.values())
    assert registry.interrupt_callback_methods == frozenset(INTERRUPT_CALLBACK_METHODS.values())
    assert registry.is_extension_method(SESSION_CONTROL_METHODS["command"]) is True


def test_extension_method_registry_omits_missing_shell_method() -> None:
    registry = ExtensionMethodRegistry.from_methods(
        {
            "list_sessions": SESSION_QUERY_METHODS["list_sessions"],
            "get_session_messages": SESSION_QUERY_METHODS["get_session_messages"],
            "prompt_async": SESSION_CONTROL_METHODS["prompt_async"],
            "command": SESSION_CONTROL_METHODS["command"],
            "reply_permission": INTERRUPT_CALLBACK_METHODS["reply_permission"],
            "reply_question": INTERRUPT_CALLBACK_METHODS["reply_question"],
            "reject_question": INTERRUPT_CALLBACK_METHODS["reject_question"],
        }
    )

    assert registry.session_control_methods == frozenset(
        {
            SESSION_CONTROL_METHODS["prompt_async"],
            SESSION_CONTROL_METHODS["command"],
        }
    )
    assert registry.is_extension_method(SESSION_CONTROL_METHODS["command"]) is True
    assert registry.is_extension_method("tasks/send") is False
