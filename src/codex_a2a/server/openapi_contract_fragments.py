from __future__ import annotations

from typing import Any

from codex_a2a.auth import has_configured_auth_scheme
from codex_a2a.config import Settings
from codex_a2a.contracts import extensions as extension_contracts
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
        "SubscribeToTask, GetExtendedAgentCard) on POST "
        f"{extension_contracts.CORE_JSONRPC_PATH}.\n\n"
        "Anonymous OpenAPI discovery intentionally exposes only the minimal shared "
        "contract surface needed for interoperable clients."
    )


def build_extension_jsonrpc_openapi_description(*, runtime_profile: RuntimeProfile) -> str:
    del runtime_profile
    interrupt_methods = ", ".join(sorted(extension_contracts.INTERRUPT_CALLBACK_METHODS.values()))
    return (
        "Provider-private Codex JSON-RPC methods also use POST "
        f"{extension_contracts.CORE_JSONRPC_PATH}, but their canonical machine-readable "
        "discovery surface is the authenticated extended Agent Card rather than this "
        "anonymous OpenAPI document.\n"
        f"Shared interrupt callback methods disclosed here: {interrupt_methods}.\n\n"
        "Notification semantics: extension requests without JSON-RPC id return HTTP 204. "
        "Unsupported methods return JSON-RPC -32601 with supported_methods and "
        "protocol_version in error.data."
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
    del runtime_profile
    return {
        "permission_reply": {
            "summary": "Reply to permission interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 31,
                "method": extension_contracts.INTERRUPT_CALLBACK_METHODS["reply_permission"],
                "params": {"request_id": "req-1", "reply": "once"},
            },
        },
        "question_reply": {
            "summary": "Reply to question interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 32,
                "method": extension_contracts.INTERRUPT_CALLBACK_METHODS["reply_question"],
                "params": {"request_id": "req-2", "answers": [["answer"]]},
            },
        },
        "question_reject": {
            "summary": "Reject question interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 33,
                "method": extension_contracts.INTERRUPT_CALLBACK_METHODS["reject_question"],
                "params": {"request_id": "req-3"},
            },
        },
        "permissions_reply": {
            "summary": "Reply to permissions interrupt request",
            "value": {
                "jsonrpc": "2.0",
                "id": 34,
                "method": extension_contracts.INTERRUPT_CALLBACK_METHODS["reply_permissions"],
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
                "method": extension_contracts.INTERRUPT_CALLBACK_METHODS["reply_elicitation"],
                "params": {
                    "request_id": "req-5",
                    "action": "accept",
                    "content": {"workspace_root": "/workspace/project"},
                },
            },
        },
    }


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
