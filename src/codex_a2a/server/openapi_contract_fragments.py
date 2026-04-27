from __future__ import annotations

from typing import Any

from codex_a2a.auth import has_configured_auth_scheme
from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import (
    CORE_JSONRPC_PATH,
    DISCOVERY_METHODS,
    EXEC_CONTROL_METHODS,
    EXTENSION_JSONRPC_PATH,
    INTERRUPT_CALLBACK_METHODS,
    INTERRUPT_RECOVERY_METHODS,
    REVIEW_CONTROL_METHODS,
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_METHODS,
    THREAD_LIFECYCLE_METHODS,
    TURN_CONTROL_METHODS,
    build_compatibility_profile_params,
    build_discovery_extension_params,
    build_exec_control_extension_params,
    build_interrupt_callback_extension_params,
    build_interrupt_recovery_extension_params,
    build_review_control_extension_params,
    build_session_binding_extension_params,
    build_session_query_extension_params,
    build_streaming_extension_params,
    build_thread_lifecycle_extension_params,
    build_turn_control_extension_params,
    build_wire_contract_extension_params,
)
from codex_a2a.profile.runtime import RuntimeProfile


def build_openapi_security(
    settings: Settings,
) -> tuple[dict[str, Any], list[dict[str, list[str]]]]:
    schemes: dict[str, Any] = {}
    security: list[dict[str, list[str]]] = []
    if has_configured_auth_scheme(settings, "bearer"):
        schemes["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque",
            "description": "Bearer token authentication",
        }
        security.append({"bearerAuth": []})
    if has_configured_auth_scheme(settings, "basic"):
        schemes["basicAuth"] = {
            "type": "http",
            "scheme": "basic",
            "description": "Basic authentication",
        }
        security.append({"basicAuth": []})
    return schemes, security


def build_core_jsonrpc_openapi_description() -> str:
    return (
        "Core A2A JSON-RPC entrypoint. Supports the standard A2A methods "
        "(SendMessage, SendStreamingMessage, GetTask, CancelTask, "
        "ListTasks, CreateTaskPushNotificationConfig, GetTaskPushNotificationConfig, "
        "ListTaskPushNotificationConfigs, DeleteTaskPushNotificationConfig, "
        f"SubscribeToTask, GetExtendedAgentCard) on POST {CORE_JSONRPC_PATH}.\n\n"
        f"Provider-private Codex extension methods are exposed separately on "
        f"POST {EXTENSION_JSONRPC_PATH}."
    )


def build_extension_jsonrpc_openapi_description(*, runtime_profile: RuntimeProfile) -> str:
    session_methods: list[str] = [
        SESSION_QUERY_METHODS["list_sessions"],
        SESSION_QUERY_METHODS["get_session_messages"],
    ]
    discovery_methods = ", ".join(DISCOVERY_METHODS.values())
    thread_lifecycle_methods = ", ".join(THREAD_LIFECYCLE_METHODS.values())
    interrupt_recovery_methods = ", ".join(INTERRUPT_RECOVERY_METHODS.values())
    turn_methods = (
        ", ".join(TURN_CONTROL_METHODS.values())
        if runtime_profile.turn_control_enabled
        else "(disabled)"
    )
    review_methods = (
        ", ".join(REVIEW_CONTROL_METHODS.values())
        if runtime_profile.review_control_enabled
        else "(disabled)"
    )
    exec_methods = (
        ", ".join(EXEC_CONTROL_METHODS.values())
        if runtime_profile.exec_control_enabled
        else "(disabled)"
    )
    interrupt_methods = ", ".join(sorted(INTERRUPT_CALLBACK_METHODS.values()))
    return (
        f"Provider-private Codex JSON-RPC extension entrypoint on POST {EXTENSION_JSONRPC_PATH}. "
        "Supports Codex session extensions, Codex thread lifecycle extensions, "
        "interrupt recovery extensions, active-turn control extensions, review "
        "control extensions, Codex discovery extensions, interactive exec "
        "extensions, and shared interrupt callback methods.\n\n"
        f"Codex session query methods: {', '.join(session_methods)}.\n"
        f"Codex thread lifecycle methods: {thread_lifecycle_methods}.\n"
        f"Codex interrupt recovery methods: {interrupt_recovery_methods}.\n"
        f"Codex active-turn control methods: {turn_methods}.\n"
        f"Codex review control methods: {review_methods}.\n"
        f"Codex discovery methods: {discovery_methods}.\n"
        f"Codex interactive exec methods: {exec_methods}.\n"
        f"Shared interrupt callback methods: {interrupt_methods}.\n\n"
        "Notification semantics: extension requests without JSON-RPC id return HTTP 204. "
        "Unsupported methods return JSON-RPC -32601 with supportedMethods and "
        "protocolVersion in error.data."
    )


def build_core_jsonrpc_openapi_examples() -> dict[str, Any]:
    return {
        "message_send": {
            "summary": "Send message via JSON-RPC core method",
            "value": {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Explain what this repository does."}],
                    }
                },
            },
        },
        "message_stream": {
            "summary": "Stream message via JSON-RPC core method",
            "value": {
                "jsonrpc": "2.0",
                "id": 102,
                "method": "SendStreamingMessage",
                "params": {
                    "message": {
                        "messageId": "msg-stream-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Stream the answer and summarize."}],
                    }
                },
            },
        },
        "authenticated_extended_card": {
            "summary": "Fetch the authenticated extended Agent Card",
            "value": {
                "jsonrpc": "2.0",
                "id": 103,
                "method": "GetExtendedAgentCard",
                "params": {},
            },
        },
    }


def build_extension_jsonrpc_openapi_examples(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    examples: dict[str, Any] = {
        "session_list": {
            "summary": "List Codex sessions",
            "value": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": SESSION_QUERY_METHODS["list_sessions"],
                "params": {"limit": SESSION_QUERY_DEFAULT_LIMIT},
            },
        },
        "session_messages": {
            "summary": "List messages for a session",
            "value": {
                "jsonrpc": "2.0",
                "id": 2,
                "method": SESSION_QUERY_METHODS["get_session_messages"],
                "params": {"session_id": "s-1", "limit": SESSION_QUERY_DEFAULT_LIMIT},
            },
        },
        "discovery_skills_list": {
            "summary": "List available Codex skills",
            "value": {
                "jsonrpc": "2.0",
                "id": 23,
                "method": DISCOVERY_METHODS["list_skills"],
                "params": {"cwds": ["/workspace/project"], "force_reload": True},
            },
        },
        "discovery_apps_list": {
            "summary": "List available Codex apps",
            "value": {
                "jsonrpc": "2.0",
                "id": 24,
                "method": DISCOVERY_METHODS["list_apps"],
                "params": {"limit": 20, "force_refetch": False},
            },
        },
        "discovery_plugins_list": {
            "summary": "List available Codex plugins",
            "value": {
                "jsonrpc": "2.0",
                "id": 25,
                "method": DISCOVERY_METHODS["list_plugins"],
                "params": {"cwds": ["/workspace/project"], "force_remote_sync": False},
            },
        },
        "discovery_plugin_read": {
            "summary": "Read one Codex plugin",
            "value": {
                "jsonrpc": "2.0",
                "id": 26,
                "method": DISCOVERY_METHODS["read_plugin"],
                "params": {
                    "marketplace_path": "/workspace/project/.codex/plugins/marketplace.json",
                    "plugin_name": "sample",
                },
            },
        },
        "discovery_watch": {
            "summary": "Watch discovery invalidation and refresh signals",
            "value": {
                "jsonrpc": "2.0",
                "id": 27,
                "method": DISCOVERY_METHODS["watch"],
                "params": {"request": {"events": ["skills.changed", "apps.updated"]}},
            },
        },
        "thread_fork": {
            "summary": "Fork a Codex thread",
            "value": {
                "jsonrpc": "2.0",
                "id": 271,
                "method": THREAD_LIFECYCLE_METHODS["fork"],
                "params": {"thread_id": "thr-1", "request": {"ephemeral": True}},
            },
        },
        "thread_archive": {
            "summary": "Archive a Codex thread",
            "value": {
                "jsonrpc": "2.0",
                "id": 272,
                "method": THREAD_LIFECYCLE_METHODS["archive"],
                "params": {"thread_id": "thr-1"},
            },
        },
        "thread_unarchive": {
            "summary": "Restore an archived Codex thread",
            "value": {
                "jsonrpc": "2.0",
                "id": 273,
                "method": THREAD_LIFECYCLE_METHODS["unarchive"],
                "params": {"thread_id": "thr-1"},
            },
        },
        "thread_metadata_update": {
            "summary": "Patch persisted Codex thread git metadata",
            "value": {
                "jsonrpc": "2.0",
                "id": 274,
                "method": THREAD_LIFECYCLE_METHODS["metadata_update"],
                "params": {
                    "thread_id": "thr-1",
                    "request": {"git_info": {"branch": "feature/thread-lifecycle"}},
                },
            },
        },
        "thread_watch": {
            "summary": "Watch thread lifecycle signals through a task stream",
            "value": {
                "jsonrpc": "2.0",
                "id": 275,
                "method": THREAD_LIFECYCLE_METHODS["watch"],
                "params": {
                    "request": {
                        "events": ["thread.started", "thread.status.changed"],
                        "thread_ids": ["thr-1"],
                    }
                },
            },
        },
        "thread_watch_release": {
            "summary": "Release an owned thread lifecycle watch task",
            "value": {
                "jsonrpc": "2.0",
                "id": 276,
                "method": THREAD_LIFECYCLE_METHODS["watch_release"],
                "params": {"task_id": "task-thread-watch-1"},
            },
        },
        "interrupts_list": {
            "summary": "List active pending interrupts for the current caller",
            "value": {
                "jsonrpc": "2.0",
                "id": 277,
                "method": INTERRUPT_RECOVERY_METHODS["list"],
                "params": {"type": "permission"},
            },
        },
        "permission_reply": {
            "summary": "Reply to permission interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 31,
                "method": INTERRUPT_CALLBACK_METHODS["reply_permission"],
                "params": {"request_id": "req-1", "reply": "once"},
            },
        },
        "question_reply": {
            "summary": "Reply to question interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 32,
                "method": INTERRUPT_CALLBACK_METHODS["reply_question"],
                "params": {"request_id": "req-2", "answers": [["answer"]]},
            },
        },
        "question_reject": {
            "summary": "Reject question interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 33,
                "method": INTERRUPT_CALLBACK_METHODS["reject_question"],
                "params": {"request_id": "req-3"},
            },
        },
        "permissions_reply": {
            "summary": "Reply to permissions interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 34,
                "method": INTERRUPT_CALLBACK_METHODS["reply_permissions"],
                "params": {
                    "request_id": "req-4",
                    "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
                    "scope": "session",
                },
            },
        },
        "elicitation_reply": {
            "summary": "Reply to elicitation interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 35,
                "method": INTERRUPT_CALLBACK_METHODS["reply_elicitation"],
                "params": {
                    "request_id": "req-5",
                    "action": "accept",
                    "content": {"workspace_root": "/workspace/project"},
                },
            },
        },
    }
    if runtime_profile.turn_control_enabled:
        examples["turn_steer"] = {
            "summary": "Append user input to the active regular turn",
            "value": {
                "jsonrpc": "2.0",
                "id": 276,
                "method": TURN_CONTROL_METHODS["steer"],
                "params": {
                    "thread_id": "thr-1",
                    "expected_turn_id": "turn-9",
                    "request": {
                        "parts": [{"type": "text", "text": "Focus on the failing tests first."}]
                    },
                },
            },
        }
    if runtime_profile.review_control_enabled:
        examples["review_start"] = {
            "summary": "Start a provider-private review turn",
            "value": {
                "jsonrpc": "2.0",
                "id": 277,
                "method": REVIEW_CONTROL_METHODS["start"],
                "params": {
                    "thread_id": "thr-1",
                    "delivery": "inline",
                    "target": {
                        "type": "commit",
                        "sha": "commit-demo-123",
                        "title": "Polish tui colors",
                    },
                },
            },
        }
        examples["review_watch"] = {
            "summary": "Watch coarse-grained review lifecycle signals through a task stream",
            "value": {
                "jsonrpc": "2.0",
                "id": 278,
                "method": REVIEW_CONTROL_METHODS["watch"],
                "params": {
                    "thread_id": "thr-1",
                    "review_thread_id": "thr-1-review",
                    "turn_id": "turn-review-1",
                    "request": {"events": ["review.started", "review.completed", "review.failed"]},
                },
            },
        }
    if runtime_profile.exec_control_enabled:
        examples["exec_start"] = {
            "summary": "Start standalone interactive command execution",
            "value": {
                "jsonrpc": "2.0",
                "id": 28,
                "method": EXEC_CONTROL_METHODS["exec_start"],
                "params": {
                    "request": {
                        "command": "bash",
                        "arguments": "-lc 'printf hello && sleep 1'",
                        "process_id": "exec-1",
                        "tty": True,
                        "rows": 24,
                        "cols": 80,
                    }
                },
            },
        }
        examples["exec_write"] = {
            "summary": "Write stdin bytes to an interactive exec session",
            "value": {
                "jsonrpc": "2.0",
                "id": 29,
                "method": EXEC_CONTROL_METHODS["exec_write"],
                "params": {"request": {"process_id": "exec-1", "delta_base64": "cHdkCg=="}},
            },
        }
        examples["exec_resize"] = {
            "summary": "Resize the interactive exec PTY",
            "value": {
                "jsonrpc": "2.0",
                "id": 30,
                "method": EXEC_CONTROL_METHODS["exec_resize"],
                "params": {"request": {"process_id": "exec-1", "rows": 40, "cols": 120}},
            },
        }
        examples["exec_terminate"] = {
            "summary": "Terminate an interactive exec session",
            "value": {
                "jsonrpc": "2.0",
                "id": 31,
                "method": EXEC_CONTROL_METHODS["exec_terminate"],
                "params": {"request": {"process_id": "exec-1"}},
            },
        }
    return examples


def build_rest_message_openapi_examples() -> dict[str, Any]:
    return {
        "basic_message": {
            "summary": "Send a basic user message (HTTP+JSON)",
            "value": {
                "message": {
                    "messageId": "msg-rest-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Explain what this repository does."}],
                }
            },
        },
        "continue_session": {
            "summary": "Continue a historical Codex session",
            "value": {
                "message": {
                    "messageId": "msg-rest-continue-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Continue previous work and summarize next steps."}],
                },
                "metadata": {"shared": {"session": {"id": "s-1"}}},
            },
        },
    }


def build_openapi_a2a_extension_contracts(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, dict[str, Any]]:
    return {
        "session_binding": build_session_binding_extension_params(runtime_profile=runtime_profile),
        "streaming": build_streaming_extension_params(),
    }


def build_openapi_codex_contracts(
    *,
    settings: Settings,
    protocol_version: str,
    runtime_profile: RuntimeProfile,
) -> dict[str, dict[str, Any]]:
    return {
        "session_query": build_session_query_extension_params(runtime_profile=runtime_profile),
        "discovery": build_discovery_extension_params(runtime_profile=runtime_profile),
        "thread_lifecycle": build_thread_lifecycle_extension_params(
            runtime_profile=runtime_profile
        ),
        "interrupt_recovery": build_interrupt_recovery_extension_params(
            runtime_profile=runtime_profile
        ),
        "turn_control": build_turn_control_extension_params(runtime_profile=runtime_profile),
        "review_control": build_review_control_extension_params(runtime_profile=runtime_profile),
        "exec_control": build_exec_control_extension_params(runtime_profile=runtime_profile),
        "interrupt_callback": build_interrupt_callback_extension_params(
            runtime_profile=runtime_profile
        ),
        "wire_contract": build_wire_contract_extension_params(
            protocol_version=protocol_version,
            supported_protocol_versions=settings.a2a_supported_protocol_versions,
            default_protocol_version=settings.a2a_protocol_version,
            runtime_profile=runtime_profile,
        ),
        "compatibility_profile": build_compatibility_profile_params(
            protocol_version=protocol_version,
            supported_protocol_versions=settings.a2a_supported_protocol_versions,
            default_protocol_version=settings.a2a_protocol_version,
            runtime_profile=runtime_profile,
        ),
    }
