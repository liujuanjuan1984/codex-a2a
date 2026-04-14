from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI

from codex_a2a.config import Settings
from codex_a2a.profile.runtime import RuntimeProfile

from .openapi_contract_fragments import (
    build_jsonrpc_extension_openapi_description,
    build_jsonrpc_extension_openapi_examples,
    build_openapi_extension_contracts,
    build_openapi_security,
    build_rest_message_openapi_examples,
)


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
        components = schema.setdefault("components", {})
        if isinstance(components, dict):
            security_schemes, security = build_openapi_security(settings)
            if security_schemes:
                components["securitySchemes"] = security_schemes
            if security:
                schema["security"] = security
        paths = schema.get("paths")
        if isinstance(paths, dict):
            root_path = paths.get("/")
            if isinstance(root_path, dict):
                post = root_path.get("post")
                if isinstance(post, dict):
                    if "security" in schema:
                        post["security"] = list(
                            cast(list[dict[str, list[str]]], schema["security"])
                        )
                    post["summary"] = "Handle A2A JSON-RPC Requests"
                    post["description"] = build_jsonrpc_extension_openapi_description(
                        runtime_profile=runtime_profile
                    )
                    post["x-a2a-extension-contracts"] = dict(extension_contracts)

                    request_body = post.setdefault("requestBody", {})
                    if isinstance(request_body, dict):
                        content = request_body.setdefault("content", {})
                        if isinstance(content, dict):
                            app_json = content.setdefault("application/json", {})
                            if isinstance(app_json, dict):
                                app_json["examples"] = build_jsonrpc_extension_openapi_examples(
                                    runtime_profile=runtime_profile
                                )

            rest_post_contracts: dict[str, dict[str, Any]] = {
                "/v1/message:send": {
                    "summary": "Send Message (HTTP+JSON)",
                    "description": (
                        "A2A HTTP+JSON message send endpoint. "
                        "Use REST payload shape with message.content and ROLE_* roles."
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
                        "Use REST payload shape with message.content and ROLE_* roles."
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
                rest_path_item = paths.get(rest_path)
                if not isinstance(rest_path_item, dict):
                    continue
                rest_post = rest_path_item.get("post")
                if not isinstance(rest_post, dict):
                    continue

                if "security" in schema:
                    rest_post["security"] = list(
                        cast(list[dict[str, list[str]]], schema["security"])
                    )
                rest_post["summary"] = contract["summary"]
                rest_post["description"] = contract["description"]
                rest_post["x-a2a-extension-contracts"] = contract["contracts"]
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
