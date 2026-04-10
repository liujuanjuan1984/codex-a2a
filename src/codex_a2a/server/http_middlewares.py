from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import cast
from urllib.parse import unquote

from a2a.server.tasks.task_store import TaskStore
from a2a.types import JSONRPCError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from codex_a2a.auth import authenticate_static_credential, build_static_auth_credentials
from codex_a2a.config import Settings
from codex_a2a.jsonrpc.errors import (
    adapt_jsonrpc_error_for_protocol,
    build_http_error_body,
    version_not_supported_error,
)
from codex_a2a.logging_context import (
    CORRELATION_ID_HEADER,
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
)
from codex_a2a.protocol_versions import (
    UnsupportedProtocolVersionError,
    negotiate_protocol_version,
    normalize_protocol_version,
    reset_current_protocol_version,
    set_current_protocol_version,
)
from codex_a2a.server.task_store import TaskStoreOperationError, task_store_failure_message

logger = logging.getLogger(__name__)

_PUBLIC_AGENT_CARD_PATHS = {
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
}
_AUTHENTICATED_EXTENDED_CARD_PATHS = {
    "/agent/authenticatedExtendedCard",
    "/v1/card",
}
_OPENAPI_PATHS = {
    "/openapi.json",
}
_REST_MESSAGE_PATHS = {
    "/v1/message:send",
    "/v1/message:stream",
}
_V1_JSONRPC_METHOD_ALIASES = {
    "CancelTask": "tasks/cancel",
    "GetExtendedAgentCard": "agent/getAuthenticatedExtendedCard",
    "GetTask": "tasks/get",
    "SendMessage": "message/send",
    "SendStreamingMessage": "message/stream",
}
GZIP_COMPRESSIBLE_PATHS = (
    _PUBLIC_AGENT_CARD_PATHS | _AUTHENTICATED_EXTENDED_CARD_PATHS | _OPENAPI_PATHS
)
PUBLIC_AGENT_CARD_CACHE_CONTROL = "public, max-age=300"
AUTHENTICATED_EXTENDED_CARD_CACHE_CONTROL = "private, max-age=300"
GZIP_MINIMUM_SIZE_BYTES = 1024


def _parse_json_body(body_bytes: bytes) -> dict | None:
    try:
        payload = json.loads(body_bytes.decode("utf-8", errors="replace"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _detect_codex_extension_method(payload: dict | None) -> str | None:
    if payload is None:
        return None
    method = payload.get("method")
    if not isinstance(method, str):
        return None
    if method.startswith("codex."):
        return method
    return None


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _is_json_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    return content_type == "application/json" or content_type.endswith("+json")


def _decode_payload_preview(body: bytes, *, limit: int) -> str:
    text = body.decode("utf-8", errors="replace")
    if limit > 0 and len(text) > limit:
        return f"{text[:limit]}...[truncated]"
    return text


def _agent_card_response_bytes(card: object) -> bytes:
    model_dump = getattr(card, "model_dump", None)
    if not callable(model_dump):  # pragma: no cover - defensive
        raise TypeError("card must provide model_dump()")
    return json.dumps(
        model_dump(
            mode="json",
            exclude_none=True,
            by_alias=True,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _build_agent_card_etag(card: object) -> str:
    return f'W/"{hashlib.sha256(_agent_card_response_bytes(card)).hexdigest()}"'


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = {item.strip() for item in if_none_match.split(",") if item.strip()}
    return "*" in candidates or etag in candidates


def _merge_vary(*values: str) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value.split(","):
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
    return ", ".join(ordered)


class PathScopedGZipMiddleware:
    """Apply gzip only to selected large text endpoints."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        paths: set[str],
        minimum_size: int = GZIP_MINIMUM_SIZE_BYTES,
        compresslevel: int = 9,
    ) -> None:
        self.app = app
        self.paths = frozenset(paths)
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") not in self.paths:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if "gzip" not in headers.get("Accept-Encoding", ""):
            await self.app(scope, receive, send)
            return

        responder = GZipResponder(
            self.app,
            self.minimum_size,
            compresslevel=self.compresslevel,
        )
        await responder(scope, receive, send)


async def _get_request_body(request: Request) -> bytes:
    body = await request.body()
    request._body = body  # allow downstream to read again
    return body


def _looks_like_jsonrpc_message_payload(payload: dict | None) -> bool:
    if payload is None:
        return False
    message = payload.get("message")
    if not isinstance(message, dict):
        return False
    if "parts" in message:
        return True
    role = message.get("role")
    return isinstance(role, str) and role in {"user", "agent"}


def _looks_like_jsonrpc_envelope(payload: dict | None) -> bool:
    if payload is None:
        return False
    method = payload.get("method")
    version = payload.get("jsonrpc")
    return isinstance(method, str) and isinstance(version, str)


def _requires_protocol_negotiation(request: Request) -> bool:
    path = request.url.path
    return request.method == "POST" and (path == "/" or path.startswith("/v1/"))


def _jsonrpc_request_id(payload: dict | None) -> str | int | None:
    if payload is None:
        return None
    request_id = payload.get("id")
    if isinstance(request_id, bool):
        return None
    if isinstance(request_id, str | int):
        return request_id
    return None


def _requested_protocol_version(request: Request) -> tuple[str | None, str | None]:
    header_value = request.headers.get("A2A-Version")
    query_value = request.query_params.get("A2A-Version")
    if query_value is None:
        query_value = request.query_params.get("a2a-version")
    return header_value, query_value


def _error_protocol_version(requested_version: str, default_protocol_version: str) -> str:
    try:
        return normalize_protocol_version(requested_version)
    except ValueError:
        return normalize_protocol_version(default_protocol_version)


def _jsonrpc_error_response(
    *,
    request_id: str | int | None,
    protocol_version: str,
    error: JSONRPCError,
) -> JSONResponse:
    adapted_error = adapt_jsonrpc_error_for_protocol(protocol_version, error)
    if not isinstance(adapted_error, JSONRPCError):  # pragma: no cover - defensive
        adapted_error = cast(JSONRPCError, adapted_error.root)
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": adapted_error.model_dump(mode="json", exclude_none=True),
        },
        status_code=200,
    )


def _unsupported_protocol_jsonrpc_response(
    *,
    request_id: str | int | None,
    exc: UnsupportedProtocolVersionError,
) -> JSONResponse:
    error_protocol_version = _error_protocol_version(
        exc.requested_version,
        exc.default_protocol_version,
    )
    return _jsonrpc_error_response(
        request_id=request_id,
        protocol_version=error_protocol_version,
        error=version_not_supported_error(
            requested_version=exc.requested_version,
            supported_protocol_versions=list(exc.supported_protocol_versions),
            default_protocol_version=exc.default_protocol_version,
        ),
    )


def _unsupported_protocol_http_response(exc: UnsupportedProtocolVersionError) -> JSONResponse:
    metadata = {
        "requested_version": exc.requested_version,
        "supported_protocol_versions": list(exc.supported_protocol_versions),
        "default_protocol_version": exc.default_protocol_version,
    }
    protocol_version = _error_protocol_version(
        exc.requested_version,
        exc.default_protocol_version,
    )
    return JSONResponse(
        build_http_error_body(
            protocol_version=protocol_version,
            status_code=400,
            status="INVALID_ARGUMENT",
            message=f"Unsupported A2A version: {exc.requested_version}",
            reason="VERSION_NOT_SUPPORTED",
            metadata=metadata,
            legacy_payload={
                "error": "Unsupported A2A version",
                **metadata,
            },
        ),
        status_code=400,
    )


async def _normalize_v1_jsonrpc_method_alias(
    request: Request,
    *,
    protocol_version: str,
) -> None:
    if protocol_version != "1.0" or request.method != "POST" or request.url.path != "/":
        return
    body = await _get_request_body(request)
    payload = _parse_json_body(body)
    if payload is None:
        return
    method = payload.get("method")
    if not isinstance(method, str):
        return
    normalized_method = _V1_JSONRPC_METHOD_ALIASES.get(method)
    if normalized_method is None:
        return
    payload = dict(payload)
    payload["method"] = normalized_method
    request._body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def install_http_middlewares(
    app: FastAPI,
    *,
    settings: Settings,
    task_store: TaskStore,
    agent_card: object,
    extended_agent_card: object,
) -> None:
    public_card_etag = _build_agent_card_etag(agent_card)
    extended_card_etag = _build_agent_card_etag(extended_agent_card)
    configured_credentials = build_static_auth_credentials(settings)
    advertised_schemes = {credential.auth_scheme for credential in configured_credentials}

    def _unauthorized_response() -> JSONResponse:
        challenges: list[str] = []
        if "bearer" in advertised_schemes:
            challenges.append("Bearer")
        if "basic" in advertised_schemes:
            challenges.append('Basic realm="codex-a2a"')
        return JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": ", ".join(challenges)},
        )

    @app.middleware("http")
    async def negotiate_a2a_protocol(request: Request, call_next):
        if not _requires_protocol_negotiation(request):
            return await call_next(request)

        header_value, query_value = _requested_protocol_version(request)
        try:
            negotiated = negotiate_protocol_version(
                header_value=header_value,
                query_value=query_value,
                default_protocol_version=settings.a2a_protocol_version,
                supported_protocol_versions=settings.a2a_supported_protocol_versions,
            )
        except UnsupportedProtocolVersionError as exc:
            request_id: str | int | None = None
            if request.method == "POST" and request.url.path == "/":
                request_id = _jsonrpc_request_id(_parse_json_body(await _get_request_body(request)))
                return _unsupported_protocol_jsonrpc_response(
                    request_id=request_id,
                    exc=exc,
                )
            return _unsupported_protocol_http_response(exc)

        request.state.a2a_requested_protocol_version = negotiated.requested_version
        request.state.a2a_protocol_version = negotiated.negotiated_version
        request.state.a2a_protocol_version_explicit = negotiated.explicit
        await _normalize_v1_jsonrpc_method_alias(
            request,
            protocol_version=negotiated.negotiated_version,
        )

        token = set_current_protocol_version(negotiated.negotiated_version)
        try:
            response = await call_next(request)
        finally:
            reset_current_protocol_version(token)
        response.headers["A2A-Version"] = negotiated.negotiated_version
        return response

    @app.middleware("http")
    async def cache_agent_card_responses(request: Request, call_next):
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path
        is_public_card = path in _PUBLIC_AGENT_CARD_PATHS
        is_extended_card = path in _AUTHENTICATED_EXTENDED_CARD_PATHS
        if not is_public_card and not is_extended_card:
            return await call_next(request)

        if is_public_card and _etag_matches(request.headers.get("if-none-match"), public_card_etag):
            return Response(
                status_code=304,
                headers={
                    "ETag": public_card_etag,
                    "Cache-Control": PUBLIC_AGENT_CARD_CACHE_CONTROL,
                    "Vary": "Accept-Encoding",
                },
            )

        response = await call_next(request)
        if response.status_code != 200:
            return response

        if is_public_card:
            response.headers["ETag"] = public_card_etag
            response.headers["Cache-Control"] = PUBLIC_AGENT_CARD_CACHE_CONTROL
            response.headers["Vary"] = _merge_vary(
                response.headers.get("Vary", ""),
                "Accept-Encoding",
            )
            return response

        response.headers["ETag"] = extended_card_etag
        response.headers["Cache-Control"] = AUTHENTICATED_EXTENDED_CARD_CACHE_CONTROL
        response.headers["Vary"] = _merge_vary(
            response.headers.get("Vary", ""),
            "Authorization",
            "Accept-Encoding",
        )
        if _etag_matches(request.headers.get("if-none-match"), extended_card_etag):
            return Response(status_code=304, headers=dict(response.headers))
        return response

    @app.middleware("http")
    async def guard_rest_payload_shape(request: Request, call_next):
        if request.method != "POST" or request.url.path not in _REST_MESSAGE_PATHS:
            return await call_next(request)

        body = await _get_request_body(request)
        payload = _parse_json_body(body)
        if _looks_like_jsonrpc_envelope(payload) or _looks_like_jsonrpc_message_payload(payload):
            return JSONResponse(
                {
                    "error": (
                        "Invalid HTTP+JSON payload for REST endpoint. "
                        "Use message.content with ROLE_* role values, or call "
                        "POST / with method=message/send or method=message/stream."
                    )
                },
                status_code=400,
            )
        return await call_next(request)

    @app.middleware("http")
    async def guard_missing_subscribe_task(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/v1/tasks/") or not path.endswith(":subscribe"):
            return await call_next(request)

        encoded_task_id = path.removeprefix("/v1/tasks/").removesuffix(":subscribe")
        task_id = unquote(encoded_task_id).strip()
        if not task_id:
            return JSONResponse({"error": "Task not found"}, status_code=404)

        try:
            task = await task_store.get(task_id)
        except TaskStoreOperationError as exc:
            logger.exception(
                "Task store operation failed while guarding subscribe path task_id=%s operation=%s",
                task_id,
                exc.operation,
            )
            return JSONResponse(
                {"error": task_store_failure_message(exc.operation)}, status_code=503
            )
        if task is None:
            return JSONResponse({"error": "Task not found", "task_id": task_id}, status_code=404)
        return await call_next(request)

    @app.middleware("http")
    async def log_payloads(request: Request, call_next):
        if not settings.a2a_log_payloads:
            return await call_next(request)

        path = request.url.path
        limit = settings.a2a_log_body_limit
        content_type = _normalize_content_type(request.headers.get("content-type"))
        content_length = _parse_content_length(request.headers.get("content-length"))

        sensitive_method: str | None = None
        request_omit_reason: str | None = None

        if not _is_json_content_type(content_type):
            request_omit_reason = f"non-json content-type={content_type or 'unknown'}"
        elif limit > 0 and content_length is None:
            request_omit_reason = f"missing content-length with limit={limit}"
        elif limit > 0 and content_length is not None and content_length > limit:
            request_omit_reason = f"content-length={content_length} exceeds limit={limit}"
        else:
            body = await _get_request_body(request)
            payload = _parse_json_body(body)
            sensitive_method = _detect_codex_extension_method(payload)

            if sensitive_method:
                logger.debug("A2A request %s %s method=%s", request.method, path, sensitive_method)
            else:
                logger.debug(
                    "A2A request %s %s body=%s",
                    request.method,
                    path,
                    _decode_payload_preview(body, limit=limit),
                )

        if request_omit_reason:
            logger.debug(
                "A2A request %s %s body=[omitted %s]",
                request.method,
                path,
                request_omit_reason,
            )

        response = await call_next(request)
        if isinstance(response, StreamingResponse):
            status_code = getattr(response, "status_code", 200)
            if request_omit_reason:
                logger.debug(
                    "A2A response %s status=%s body=[omitted request_%s]",
                    path,
                    status_code,
                    request_omit_reason,
                )
            elif sensitive_method:
                logger.debug("A2A response %s streaming method=%s", path, sensitive_method)
            else:
                logger.debug("A2A response %s streaming", path)
            return response

        response_body = getattr(response, "body", b"") or b""
        if sensitive_method:
            logger.debug(
                "A2A response %s status=%s bytes=%s method=%s",
                path,
                response.status_code,
                len(response_body),
                sensitive_method,
            )
            return response

        if request_omit_reason:
            logger.debug(
                "A2A response %s status=%s bytes=%s body=[omitted request_%s]",
                path,
                response.status_code,
                len(response_body),
                request_omit_reason,
            )
            return response

        response_content_type = _normalize_content_type(response.headers.get("content-type"))
        if not _is_json_content_type(response_content_type):
            logger.debug(
                "A2A response %s status=%s bytes=%s body=[omitted non-json content-type=%s]",
                path,
                response.status_code,
                len(response_body),
                response_content_type or "unknown",
            )
            return response

        logger.debug(
            "A2A response %s status=%s body=%s",
            path,
            response.status_code,
            _decode_payload_preview(response_body, limit=limit),
        )
        return response

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in _PUBLIC_AGENT_CARD_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        try:
            auth_scheme, auth_value = auth_header.split(" ", 1)
        except ValueError:
            return _unauthorized_response()
        principal = authenticate_static_credential(
            credentials=configured_credentials,
            auth_scheme=auth_scheme,
            auth_value=auth_value.strip(),
        )
        if principal is None:
            return _unauthorized_response()
        request.state.authenticated_principal = principal
        request.state.user_identity = principal.identity
        request.state.user_auth_scheme = principal.auth_scheme
        if principal.credential_id:
            request.state.user_credential_id = principal.credential_id

        return await call_next(request)

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        correlation_id = resolve_correlation_id(request.headers.get("x-request-id"))
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        started_at = time.perf_counter()
        path = request.url.path
        logger.debug("A2A request started method=%s path=%s", request.method, path)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            logger.debug(
                "A2A request completed method=%s path=%s status=%s duration_ms=%.2f",
                request.method,
                path,
                response.status_code,
                (time.perf_counter() - started_at) * 1000.0,
            )
            return response
        except Exception:
            logger.exception(
                "A2A request failed method=%s path=%s duration_ms=%.2f",
                request.method,
                path,
                (time.perf_counter() - started_at) * 1000.0,
            )
            raise
        finally:
            reset_correlation_id(token)
