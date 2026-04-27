from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI

from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import CORE_JSONRPC_PATH, EXTENSION_JSONRPC_PATH
from codex_a2a.profile.runtime import RuntimeProfile

from .openapi_contract_fragments import (
    build_core_jsonrpc_openapi_description,
    build_core_jsonrpc_openapi_examples,
    build_extension_jsonrpc_openapi_description,
    build_extension_jsonrpc_openapi_examples,
    build_openapi_extension_contracts,
    build_openapi_security,
    build_rest_message_openapi_examples,
)


def _ensure_object_schema(
    schemas: dict[str, Any],
    name: str,
    schema: dict[str, Any],
) -> None:
    if name not in schemas:
        schemas[name] = schema


def _ensure_minimal_a2a_schemas(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    if not isinstance(components, dict):
        return
    schemas = components.setdefault("schemas", {})
    if not isinstance(schemas, dict):
        return

    _ensure_object_schema(
        schemas,
        "A2APart",
        {
            "type": "object",
            "description": (
                "A2A 1.0 part payload. Text parts use {'text': '...'}; "
                "file and data parts use the matching protobuf JSON field names."
            ),
            "additionalProperties": True,
        },
    )
    _ensure_object_schema(
        schemas,
        "A2AMessage",
        {
            "type": "object",
            "required": ["messageId", "role", "parts"],
            "properties": {
                "messageId": {"type": "string"},
                "role": {"type": "string", "enum": ["ROLE_USER", "ROLE_AGENT"]},
                "parts": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/A2APart"},
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        },
    )
    _ensure_object_schema(
        schemas,
        "SendMessageRequest",
        {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"$ref": "#/components/schemas/A2AMessage"},
                "configuration": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "metadata": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        },
    )
    _ensure_object_schema(
        schemas,
        "SendStreamingMessageRequest",
        {
            "$ref": "#/components/schemas/SendMessageRequest",
        },
    )
    _ensure_object_schema(
        schemas,
        "A2AJsonRpcRequest",
        {
            "type": "object",
            "required": ["jsonrpc", "method"],
            "properties": {
                "jsonrpc": {"type": "string", "enum": ["2.0"]},
                "id": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ]
                },
                "method": {"type": "string"},
                "params": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        },
    )


def _ensure_path_item(
    paths: dict[str, Any],
    path: str,
    method: str,
) -> dict[str, Any]:
    path_item = paths.setdefault(path, {})
    if not isinstance(path_item, dict):
        path_item = {}
        paths[path] = path_item
    operation = path_item.setdefault(method, {})
    if not isinstance(operation, dict):
        operation = {}
        path_item[method] = operation
    return operation


def patch_openapi_contract(
    app: FastAPI,
    *,
    settings: Settings,
    protocol_version: str,
    runtime_profile: RuntimeProfile,
) -> None:
    extension_contracts = build_openapi_extension_contracts(
        settings=settings,
        protocol_version=protocol_version,
        runtime_profile=runtime_profile,
    )
    original_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = original_openapi()
        _ensure_minimal_a2a_schemas(schema)
        components = schema.setdefault("components", {})
        if isinstance(components, dict):
            security_schemes, security = build_openapi_security(settings)
            if security_schemes:
                components["securitySchemes"] = security_schemes
            if security:
                schema["security"] = security
        paths = schema.setdefault("paths", {})
        if isinstance(paths, dict):
            core_contracts = {
                "session_binding": extension_contracts["session_binding"],
                "streaming": extension_contracts["streaming"],
                "wire_contract": extension_contracts["wire_contract"],
                "compatibility_profile": extension_contracts["compatibility_profile"],
            }
            extension_only_contracts = {
                "session_query": extension_contracts["session_query"],
                "discovery": extension_contracts["discovery"],
                "thread_lifecycle": extension_contracts["thread_lifecycle"],
                "interrupt_recovery": extension_contracts["interrupt_recovery"],
                "turn_control": extension_contracts["turn_control"],
                "review_control": extension_contracts["review_control"],
                "exec_control": extension_contracts["exec_control"],
                "interrupt_callback": extension_contracts["interrupt_callback"],
                "wire_contract": extension_contracts["wire_contract"],
                "compatibility_profile": extension_contracts["compatibility_profile"],
            }

            post = _ensure_path_item(paths, CORE_JSONRPC_PATH, "post")
            if "security" in schema:
                post["security"] = list(cast(list[dict[str, list[str]]], schema["security"]))
            post["summary"] = "Handle Core A2A JSON-RPC Requests"
            post["description"] = build_core_jsonrpc_openapi_description()
            post["x-a2a-extension-contracts"] = core_contracts
            post.setdefault("responses", {"200": {"description": "JSON-RPC response"}})

            request_body = post.setdefault("requestBody", {})
            if isinstance(request_body, dict):
                request_body.setdefault("required", True)
                content = request_body.setdefault("content", {})
                if isinstance(content, dict):
                    app_json = content.setdefault("application/json", {})
                    if isinstance(app_json, dict):
                        app_json.setdefault(
                            "schema",
                            {"$ref": "#/components/schemas/A2AJsonRpcRequest"},
                        )
                        app_json["examples"] = build_core_jsonrpc_openapi_examples()

            extension_post = _ensure_path_item(paths, EXTENSION_JSONRPC_PATH, "post")
            if "security" in schema:
                extension_post["security"] = list(
                    cast(list[dict[str, list[str]]], schema["security"])
                )
            extension_post["summary"] = "Handle Codex Extension JSON-RPC Requests"
            extension_post["description"] = build_extension_jsonrpc_openapi_description(
                runtime_profile=runtime_profile
            )
            extension_post["x-a2a-extension-contracts"] = extension_only_contracts
            extension_post.setdefault("responses", {"200": {"description": "JSON-RPC response"}})

            extension_request_body = extension_post.setdefault("requestBody", {})
            if isinstance(extension_request_body, dict):
                extension_request_body.setdefault("required", True)
                extension_content = extension_request_body.setdefault("content", {})
                if isinstance(extension_content, dict):
                    extension_app_json = extension_content.setdefault("application/json", {})
                    if isinstance(extension_app_json, dict):
                        extension_app_json.setdefault(
                            "schema",
                            {"$ref": "#/components/schemas/A2AJsonRpcRequest"},
                        )
                        extension_app_json["examples"] = build_extension_jsonrpc_openapi_examples(
                            runtime_profile=runtime_profile
                        )

            rest_post_contracts: dict[str, dict[str, Any]] = {
                "/v1/message:send": {
                    "summary": "Send Message (HTTP+JSON)",
                    "description": (
                        "A2A HTTP+JSON message send endpoint. "
                        "Use the A2A 1.0 request body with message.parts."
                    ),
                    "schema_ref": "#/components/schemas/SendMessageRequest",
                    "contracts": {
                        "session_binding": extension_contracts["session_binding"],
                    },
                },
                "/v1/message:stream": {
                    "summary": "Stream Message (HTTP+JSON)",
                    "description": (
                        "A2A HTTP+JSON streaming endpoint. "
                        "Use the A2A 1.0 request body with message.parts."
                    ),
                    "schema_ref": "#/components/schemas/SendStreamingMessageRequest",
                    "contracts": {
                        "session_binding": extension_contracts["session_binding"],
                        "streaming": extension_contracts["streaming"],
                        "interrupt_callback": extension_contracts["interrupt_callback"],
                    },
                },
            }
            rest_examples = build_rest_message_openapi_examples()
            for rest_path, contract in rest_post_contracts.items():
                rest_post = _ensure_path_item(paths, rest_path, "post")

                if "security" in schema:
                    rest_post["security"] = list(
                        cast(list[dict[str, list[str]]], schema["security"])
                    )
                rest_post["summary"] = contract["summary"]
                rest_post["description"] = contract["description"]
                rest_post["x-a2a-extension-contracts"] = contract["contracts"]
                rest_post.setdefault("responses", {"200": {"description": "A2A response"}})
                if rest_path == "/v1/message:stream":
                    rest_post["x-a2a-streaming"] = extension_contracts["streaming"]

                request_body = rest_post.setdefault("requestBody", {})
                if not isinstance(request_body, dict):
                    continue
                request_body.setdefault("required", True)
                content = request_body.setdefault("content", {})
                if not isinstance(content, dict):
                    continue
                app_json = content.setdefault("application/json", {})
                if not isinstance(app_json, dict):
                    continue
                app_json["schema"] = {"$ref": contract["schema_ref"]}
                app_json["examples"] = rest_examples

        app.openapi_schema = schema
        return schema

    cast(Any, app).openapi = custom_openapi
