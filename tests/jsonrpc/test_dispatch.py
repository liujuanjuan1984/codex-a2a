import pytest

from codex_a2a.contracts.extensions import (
    DISCOVERY_EXTENSION_URI,
    DISCOVERY_METHODS,
    EXEC_CONTROL_EXTENSION_URI,
    EXEC_CONTROL_METHODS,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    INTERRUPT_CALLBACK_METHODS,
    INTERRUPT_RECOVERY_EXTENSION_URI,
    INTERRUPT_RECOVERY_METHODS,
    REVIEW_CONTROL_EXTENSION_URI,
    REVIEW_CONTROL_METHODS,
    SESSION_QUERY_EXTENSION_URI,
    SESSION_QUERY_METHODS,
    THREAD_LIFECYCLE_EXTENSION_URI,
    THREAD_LIFECYCLE_METHODS,
    TURN_CONTROL_EXTENSION_URI,
    TURN_CONTROL_METHODS,
)
from codex_a2a.jsonrpc.dispatch import ExtensionMethodRegistry


def test_extension_method_registry_partitions_methods() -> None:
    registry = ExtensionMethodRegistry.from_methods(
        {
            **SESSION_QUERY_METHODS,
            **DISCOVERY_METHODS,
            "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
            "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
            "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
            "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
            "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
            "thread_watch_release": THREAD_LIFECYCLE_METHODS["watch_release"],
            "interrupts_list": INTERRUPT_RECOVERY_METHODS["list"],
            "turn_steer": TURN_CONTROL_METHODS["steer"],
            "review_start": REVIEW_CONTROL_METHODS["start"],
            "review_watch": REVIEW_CONTROL_METHODS["watch"],
            **EXEC_CONTROL_METHODS,
            **INTERRUPT_CALLBACK_METHODS,
        }
    )

    assert registry.session_query_methods == frozenset(
        {
            SESSION_QUERY_METHODS["list_sessions"],
            SESSION_QUERY_METHODS["get_session_messages"],
        }
    )
    assert registry.discovery_query_methods == frozenset(
        {
            DISCOVERY_METHODS["list_skills"],
            DISCOVERY_METHODS["list_apps"],
            DISCOVERY_METHODS["list_plugins"],
            DISCOVERY_METHODS["read_plugin"],
        }
    )
    assert registry.discovery_control_methods == frozenset({DISCOVERY_METHODS["watch"]})
    assert registry.thread_lifecycle_control_methods == frozenset(THREAD_LIFECYCLE_METHODS.values())
    assert registry.interrupt_recovery_methods == frozenset(INTERRUPT_RECOVERY_METHODS.values())
    assert registry.turn_control_methods == frozenset(TURN_CONTROL_METHODS.values())
    assert registry.review_control_methods == frozenset(REVIEW_CONTROL_METHODS.values())
    assert registry.exec_control_methods == frozenset(EXEC_CONTROL_METHODS.values())
    assert registry.interrupt_callback_methods == frozenset(INTERRUPT_CALLBACK_METHODS.values())
    assert registry.is_extension_method(SESSION_QUERY_METHODS["list_sessions"]) is True
    assert registry.is_extension_method(THREAD_LIFECYCLE_METHODS["watch"]) is True
    assert registry.is_extension_method(TURN_CONTROL_METHODS["steer"]) is True
    assert registry.is_extension_method(EXEC_CONTROL_METHODS["exec_start"]) is True
    expected_extension_uris = {
        **{method: SESSION_QUERY_EXTENSION_URI for method in registry.session_query_methods},
        **{
            method: DISCOVERY_EXTENSION_URI
            for method in registry.discovery_query_methods | registry.discovery_control_methods
        },
        **{
            method: THREAD_LIFECYCLE_EXTENSION_URI
            for method in registry.thread_lifecycle_control_methods
        },
        **{
            method: INTERRUPT_RECOVERY_EXTENSION_URI
            for method in registry.interrupt_recovery_methods
        },
        **{method: TURN_CONTROL_EXTENSION_URI for method in registry.turn_control_methods},
        **{method: REVIEW_CONTROL_EXTENSION_URI for method in registry.review_control_methods},
        **{method: EXEC_CONTROL_EXTENSION_URI for method in registry.exec_control_methods},
        **{
            method: INTERRUPT_CALLBACK_EXTENSION_URI
            for method in registry.interrupt_callback_methods
        },
    }
    assert registry.extension_uri_by_method == expected_extension_uris
    assert registry.extension_uri_for_method("SendMessage") is None


def test_extension_method_registry_without_optional_surfaces() -> None:
    registry = ExtensionMethodRegistry.from_methods(
        {
            "list_sessions": SESSION_QUERY_METHODS["list_sessions"],
            "get_session_messages": SESSION_QUERY_METHODS["get_session_messages"],
            "list_skills": DISCOVERY_METHODS["list_skills"],
            "list_apps": DISCOVERY_METHODS["list_apps"],
            "watch": DISCOVERY_METHODS["watch"],
            "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
            "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
            "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
            "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
            "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
            "thread_watch_release": THREAD_LIFECYCLE_METHODS["watch_release"],
            "interrupts_list": INTERRUPT_RECOVERY_METHODS["list"],
            "turn_steer": TURN_CONTROL_METHODS["steer"],
            "review_start": REVIEW_CONTROL_METHODS["start"],
            "review_watch": REVIEW_CONTROL_METHODS["watch"],
            **EXEC_CONTROL_METHODS,
            "reply_permission": INTERRUPT_CALLBACK_METHODS["reply_permission"],
            "reply_question": INTERRUPT_CALLBACK_METHODS["reply_question"],
            "reject_question": INTERRUPT_CALLBACK_METHODS["reject_question"],
            "reply_permissions": INTERRUPT_CALLBACK_METHODS["reply_permissions"],
            "reply_elicitation": INTERRUPT_CALLBACK_METHODS["reply_elicitation"],
        }
    )

    assert registry.discovery_query_methods == frozenset(
        {
            DISCOVERY_METHODS["list_skills"],
            DISCOVERY_METHODS["list_apps"],
        }
    )
    assert registry.discovery_control_methods == frozenset({DISCOVERY_METHODS["watch"]})
    assert registry.thread_lifecycle_control_methods == frozenset(THREAD_LIFECYCLE_METHODS.values())
    assert registry.interrupt_recovery_methods == frozenset(INTERRUPT_RECOVERY_METHODS.values())
    assert registry.turn_control_methods == frozenset(TURN_CONTROL_METHODS.values())
    assert registry.review_control_methods == frozenset(REVIEW_CONTROL_METHODS.values())
    assert registry.exec_control_methods == frozenset(EXEC_CONTROL_METHODS.values())
    assert registry.is_extension_method(SESSION_QUERY_METHODS["get_session_messages"]) is True
    assert registry.is_extension_method(THREAD_LIFECYCLE_METHODS["fork"]) is True
    assert registry.is_extension_method("tasks/send") is False


def test_extension_method_registry_rejects_cross_extension_method_collisions() -> None:
    methods = {
        **SESSION_QUERY_METHODS,
        **DISCOVERY_METHODS,
        "thread_fork": THREAD_LIFECYCLE_METHODS["fork"],
        "thread_archive": THREAD_LIFECYCLE_METHODS["archive"],
        "thread_unarchive": THREAD_LIFECYCLE_METHODS["unarchive"],
        "thread_metadata_update": THREAD_LIFECYCLE_METHODS["metadata_update"],
        "thread_watch": THREAD_LIFECYCLE_METHODS["watch"],
        "thread_watch_release": THREAD_LIFECYCLE_METHODS["watch_release"],
        "interrupts_list": INTERRUPT_RECOVERY_METHODS["list"],
        "turn_steer": TURN_CONTROL_METHODS["steer"],
        "review_start": REVIEW_CONTROL_METHODS["start"],
        "review_watch": REVIEW_CONTROL_METHODS["watch"],
        **EXEC_CONTROL_METHODS,
        **INTERRUPT_CALLBACK_METHODS,
    }
    methods["list_skills"] = methods["list_sessions"]

    with pytest.raises(ValueError, match="maps to multiple extension URIs"):
        ExtensionMethodRegistry.from_methods(methods)
