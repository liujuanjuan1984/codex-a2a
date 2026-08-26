from __future__ import annotations

from typing import Any

METHOD_EXTENSION_NEGOTIATION_ERROR_CODE = -32004
METHOD_EXTENSION_NEGOTIATION_ERROR_REASON = "EXTENSION_NEGOTIATION_REQUIRED"
METHOD_EXTENSION_POLICY_ERROR_CODE = -32004
METHOD_EXTENSION_POLICY_ERROR_REASON = "EXTENSION_ACTIVATION_FORBIDDEN"

METHOD_EXTENSION_ACTIVATION_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "method",
    "required_extensions",
    "requested_extensions",
    "header",
)
METHOD_EXTENSION_POLICY_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "method",
    "extension_uri",
    "capability",
)


def build_method_extension_activation_contract(extension_uri: str) -> dict[str, Any]:
    return {
        "mode": "request_level",
        "request_header": "A2A-Extensions",
        "response_header": "A2A-Extensions",
        "required_extension_uri": extension_uri,
        "policy": {
            "checks": [
                "method_enabled_for_deployment",
                "extension_explicitly_requested",
                "extension_authorized_for_call_context",
            ],
            "default_authorization": "allow_after_transport_authentication",
            "authorization_hook": "deployment_injectable_sync_or_async",
        },
        "response_behavior": {
            "echo": "all_extensions_activated_for_request",
            "ignore_requested_but_inactive_extensions": True,
        },
        "errors": {
            "negotiation_required": {
                "a2a_error_type": "UnsupportedOperationError",
                "jsonrpc_code": METHOD_EXTENSION_NEGOTIATION_ERROR_CODE,
                "reason": METHOD_EXTENSION_NEGOTIATION_ERROR_REASON,
                "data_fields": list(METHOD_EXTENSION_ACTIVATION_ERROR_DATA_FIELDS),
                "convention": "codex-a2a",
            },
            "activation_forbidden": {
                "a2a_error_type": "UnsupportedOperationError",
                "jsonrpc_code": METHOD_EXTENSION_POLICY_ERROR_CODE,
                "reason": METHOD_EXTENSION_POLICY_ERROR_REASON,
                "data_fields": list(METHOD_EXTENSION_POLICY_ERROR_DATA_FIELDS),
                "convention": "codex-a2a",
            },
            "policy_evaluation_failed": {
                "a2a_error_type": "InternalError",
                "jsonrpc_code": -32603,
                "convention": "A2A_JSON_RPC",
            },
        },
    }
