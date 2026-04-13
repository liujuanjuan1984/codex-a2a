from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from a2a.types import A2AError, InternalError, JSONRPCError, JSONRPCRequest
from starlette.responses import Response

from codex_a2a.jsonrpc.discovery_params import (
    parse_discovery_apps_list_params,
    parse_discovery_plugin_read_params,
    parse_discovery_plugins_list_params,
    parse_discovery_skills_list_params,
)
from codex_a2a.jsonrpc.discovery_payload_mapping import (
    map_apps_list,
    map_plugin_detail,
    map_plugin_marketplaces,
    map_skill_scopes,
)
from codex_a2a.jsonrpc.errors import (
    ERR_UPSTREAM_PAYLOAD_ERROR,
    invalid_params_response,
    upstream_http_error_response,
    upstream_unreachable_response,
)
from codex_a2a.jsonrpc.params_common import JsonRpcParamsValidationError

if TYPE_CHECKING:
    from codex_a2a.jsonrpc.application import CodexSessionQueryJSONRPCApplication

logger = logging.getLogger(__name__)


async def handle_discovery_query_request(
    app: CodexSessionQueryJSONRPCApplication,
    base_request: JSONRPCRequest,
    params: dict[str, Any],
) -> Response:
    try:
        if base_request.method == app._method_discovery_skills_list:
            rpc_params = parse_discovery_skills_list_params(params)
            raw_result = await app._codex_client.list_skills(params=rpc_params)
            result: dict[str, Any] = {"items": map_skill_scopes(raw_result)}
        elif base_request.method == app._method_discovery_apps_list:
            rpc_params = parse_discovery_apps_list_params(params)
            raw_result = await app._codex_client.list_apps(params=rpc_params)
            items, next_cursor = map_apps_list(raw_result)
            result = {"items": items, "next_cursor": next_cursor}
        elif base_request.method == app._method_discovery_plugins_list:
            rpc_params = parse_discovery_plugins_list_params(params)
            raw_result = await app._codex_client.list_plugins(params=rpc_params)
            result = map_plugin_marketplaces(raw_result)
        else:
            rpc_params = parse_discovery_plugin_read_params(params)
            raw_result = await app._codex_client.read_plugin(params=rpc_params)
            result = {"item": map_plugin_detail(raw_result)}
    except JsonRpcParamsValidationError as exc:
        return invalid_params_response(app, base_request.id, exc)
    except httpx.HTTPStatusError as exc:
        return upstream_http_error_response(
            app,
            base_request.id,
            upstream_status=exc.response.status_code,
            data={"method": base_request.method},
        )
    except httpx.HTTPError:
        return upstream_unreachable_response(
            app,
            base_request.id,
            data={"method": base_request.method},
        )
    except ValueError as exc:
        logger.warning("Upstream Codex discovery payload mismatch: %s", exc)
        return app._generate_error_response(
            base_request.id,
            JSONRPCError(
                code=ERR_UPSTREAM_PAYLOAD_ERROR,
                message="Upstream Codex payload mismatch",
                data={
                    "type": "UPSTREAM_PAYLOAD_ERROR",
                    "method": base_request.method,
                    "detail": str(exc),
                },
            ),
        )
    except Exception as exc:
        logger.exception("Codex discovery JSON-RPC method failed")
        return app._generate_error_response(
            base_request.id,
            A2AError(root=InternalError(message=str(exc))),
        )

    if base_request.id is None:
        return Response(status_code=204)
    return app._jsonrpc_success_response(base_request.id, result)
