from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from a2a.server.context import ServerCallContext
from a2a.server.jsonrpc_models import JSONRPCError
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.tasks.task_store import TaskStore
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder
from starlette.responses import Response, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from codex_a2a.auth import (
    StaticAuthCredential,
    authenticate_static_credential,
    build_static_auth_credentials,
)
from codex_a2a.client.network_policy import matches_allowed_host
from codex_a2a.config import Settings
from codex_a2a.contracts import extensions as extension_contracts
from codex_a2a.jsonrpc.errors import (
    adapt_jsonrpc_error,
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
    reset_current_protocol_version,
    set_current_protocol_version,
)
from codex_a2a.server.task_store import TaskStoreOperationError, task_store_failure_message

logger = logging.getLogger(__name__)

_PUBLIC_AGENT_CARD_PATHS = {
    "/.well-known/agent-card.json",
}
_AUTHENTICATED_EXTENDED_CARD_PATHS = {
    "/extendedAgentCard",
}
_OPENAPI_PATHS = {
    "/openapi.json",
}
_REST_MESSAGE_PATHS = {
    "/message:send",
    "/message:stream",
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
    return json.dumps(
        agent_card_to_dict(cast(Any, card)),
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


def _origin_of_url(value: str) -> str | None:
    """Return the normalized ``scheme://host[:port]`` origin of a URL."""

    parsed = urlsplit((value or "").strip())
    scheme = (parsed.scheme or "").lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    hostname = hostname.lower()
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return f"{scheme}://{hostname}"
    return f"{scheme}://{hostname}:{port}"


def _normalized_origins(values: list[str] | tuple[str, ...] | None) -> set[str]:
    normalized: set[str] = set()
    for raw in values or ():
        value = (raw or "").strip().lower().rstrip("/")
        if value:
            normalized.add(value)
    return normalized


_LOOPBACK_BIND_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_loopback_bind(host: str) -> bool:
    normalized = (host or "").strip().lower()
    if normalized in _LOOPBACK_BIND_HOSTS:
        return True
    return normalized.startswith("127.")


def _hostname_from_host_header(host: str) -> str:
    try:
        parsed = urlsplit(f"//{host.strip()}")
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def _boundary_rejection_response(message: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": 403,
                "status": "FORBIDDEN",
                "message": message,
            }
        },
        status_code=403,
    )


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


def _looks_like_jsonrpc_envelope(payload: dict | None) -> bool:
    if payload is None:
        return False
    method = payload.get("method")
    version = payload.get("jsonrpc")
    return isinstance(method, str) and isinstance(version, str)


def _is_jsonrpc_path(path: str) -> bool:
    return path in {
        extension_contracts.CORE_JSONRPC_PATH,
        extension_contracts.EXTENSION_JSONRPC_PATH,
    }


def _is_rest_path(path: str) -> bool:
    return (
        path in _REST_MESSAGE_PATHS
        or path in _AUTHENTICATED_EXTENDED_CARD_PATHS
        or path == "/tasks"
        or path.startswith("/tasks/")
    )


def _canonical_rest_path(path: str) -> str:
    # The HTTP+JSON surface is rooted at the service root (A2A 1.0 resolves
    # REST paths from the advertised interface URL, with no version prefix in
    # the URL). A single leading tenant segment from the SDK's legacy alias
    # layout is canonicalized away for middleware classification; the route
    # layer still rejects those aliases.
    if _is_rest_path(path):
        return path
    tenant_end = path.find("/", 1)
    if tenant_end > 0 and "/" not in path[1:tenant_end]:
        candidate = path[tenant_end:]
        if _is_rest_path(candidate):
            return candidate
    return path


def _requires_protocol_negotiation(request: Request) -> bool:
    path = _canonical_rest_path(request.url.path)
    if request.method == "OPTIONS":
        return False
    return _is_jsonrpc_path(path) or _is_rest_path(path)


def _jsonrpc_request_id(payload: dict | None) -> str | int | None:
    if payload is None:
        return None
    request_id = payload.get("id")
    if isinstance(request_id, bool):
        return None
    if isinstance(request_id, str | int):
        return request_id
    return None


def _jsonrpc_error_response(
    *,
    request_id: str | int | None,
    error: JSONRPCError,
) -> JSONResponse:
    adapted_error = adapt_jsonrpc_error(error)
    error_payload = (
        adapted_error.model_dump(mode="json", exclude_none=True)
        if isinstance(adapted_error, JSONRPCError)
        else {"code": -32603, "message": str(adapted_error)}
    )
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error_payload,
        },
        status_code=200,
    )


def _unsupported_protocol_http_response(exc: UnsupportedProtocolVersionError) -> JSONResponse:
    metadata = {
        "requested_version": exc.requested_version,
        "supported_protocol_versions": list(exc.supported_protocol_versions),
        "default_protocol_version": exc.default_protocol_version,
    }
    return JSONResponse(
        build_http_error_body(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=f"Unsupported A2A version: {exc.requested_version}",
            reason="VERSION_NOT_SUPPORTED",
            metadata=metadata,
        ),
        status_code=400,
    )


def _inject_context_protocol_header(
    request: Request,
    *,
    protocol_version: str,
) -> None:
    if request.headers.get("A2A-Version"):
        return
    headers = list(request.scope.get("headers", []))
    headers.append((b"a2a-version", protocol_version.encode("utf-8")))
    request.scope["headers"] = headers
    request._headers = Headers(raw=headers)


def _unauthorized_response(advertised_schemes: set[str]) -> JSONResponse:
    challenges: list[str] = []
    if "bearer" in advertised_schemes:
        challenges.append("Bearer")
    if "basic" in advertised_schemes:
        challenges.append('Basic realm="codex-a2a"')
    return JSONResponse(
        {
            "error": {
                "code": 401,
                "status": "UNAUTHORIZED",
                "message": "Unauthorized",
            }
        },
        status_code=401,
        headers={"WWW-Authenticate": ", ".join(challenges)},
    )


def _install_protocol_negotiation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def negotiate_a2a_protocol(request: Request, call_next):
        if not _requires_protocol_negotiation(request):
            return await call_next(request)

        header_value = request.headers.get("A2A-Version")
        query_value = request.query_params.get("A2A-Version")
        if query_value is None:
            query_value = request.query_params.get("a2a-version")
        try:
            negotiated = negotiate_protocol_version(
                header_value=header_value,
                query_value=query_value,
            )
        except UnsupportedProtocolVersionError as exc:
            request_id: str | int | None = None
            if request.method == "POST" and _is_jsonrpc_path(request.url.path):
                request_id = _jsonrpc_request_id(_parse_json_body(await _get_request_body(request)))
                return _jsonrpc_error_response(
                    request_id=request_id,
                    error=version_not_supported_error(
                        requested_version=exc.requested_version,
                        supported_protocol_versions=list(exc.supported_protocol_versions),
                        default_protocol_version=exc.default_protocol_version,
                    ),
                )
            return _unsupported_protocol_http_response(exc)

        _inject_context_protocol_header(
            request,
            protocol_version=negotiated.protocol_version,
        )

        token = set_current_protocol_version(negotiated.protocol_version)
        try:
            response = await call_next(request)
        finally:
            reset_current_protocol_version(token)
        response.headers["A2A-Version"] = negotiated.protocol_version
        return response


def _install_agent_card_cache_middleware(
    app: FastAPI,
    *,
    public_card_etag: str,
    extended_card_etag: str,
) -> None:
    @app.middleware("http")
    async def cache_agent_card_responses(request: Request, call_next):
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path
        canonical_path = _canonical_rest_path(path)
        is_public_card = path in _PUBLIC_AGENT_CARD_PATHS
        is_extended_card = canonical_path in _AUTHENTICATED_EXTENDED_CARD_PATHS
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


def _install_rest_payload_shape_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard_rest_payload_shape(request: Request, call_next):
        if (
            request.method != "POST"
            or _canonical_rest_path(request.url.path) not in _REST_MESSAGE_PATHS
        ):
            return await call_next(request)

        body = await _get_request_body(request)
        payload = _parse_json_body(body)
        if _looks_like_jsonrpc_envelope(payload):
            return JSONResponse(
                {
                    "error": (
                        "Invalid HTTP+JSON payload for REST endpoint. "
                        "Use an A2A 1.0 request body with message.parts, or call "
                        f"POST {extension_contracts.CORE_JSONRPC_PATH} "
                        "with JSON-RPC method=SendMessage or "
                        "method=SendStreamingMessage."
                    )
                },
                status_code=400,
            )
        return await call_next(request)


def _install_subscribe_task_guard(app: FastAPI, *, task_store: TaskStore) -> None:
    @app.middleware("http")
    async def guard_missing_subscribe_task(request: Request, call_next):
        path = _canonical_rest_path(request.url.path)
        if not path.startswith("/tasks/") or not path.endswith(":subscribe"):
            return await call_next(request)

        encoded_task_id = path.removeprefix("/tasks/").removesuffix(":subscribe")
        task_id = unquote(encoded_task_id).strip()
        if not task_id:
            return JSONResponse({"error": "Task not found"}, status_code=404)

        try:
            task = await task_store.get(task_id, ServerCallContext())
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


async def _payload_request_log_info(
    request: Request,
    *,
    settings: Settings,
) -> tuple[str | None, str | None]:
    """Compute the sensitive-method/omit decision and log the request line."""
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
    return sensitive_method, request_omit_reason


def _payload_response_log(
    response: Response,
    *,
    path: str,
    sensitive_method: str | None,
    request_omit_reason: str | None,
    limit: int,
) -> None:
    """Log a response according to its content and sensitivity."""
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
        return

    response_body = getattr(response, "body", b"") or b""
    if sensitive_method:
        logger.debug(
            "A2A response %s status=%s bytes=%s method=%s",
            path,
            response.status_code,
            len(response_body),
            sensitive_method,
        )
        return
    if request_omit_reason:
        logger.debug(
            "A2A response %s status=%s bytes=%s body=[omitted request_%s]",
            path,
            response.status_code,
            len(response_body),
            request_omit_reason,
        )
        return

    response_content_type = _normalize_content_type(response.headers.get("content-type"))
    if not _is_json_content_type(response_content_type):
        logger.debug(
            "A2A response %s status=%s bytes=%s body=[omitted non-json content-type=%s]",
            path,
            response.status_code,
            len(response_body),
            response_content_type or "unknown",
        )
        return

    logger.debug(
        "A2A response %s status=%s body=%s",
        path,
        response.status_code,
        _decode_payload_preview(response_body, limit=limit),
    )


def _install_payload_logging_middleware(app: FastAPI, *, settings: Settings) -> None:
    @app.middleware("http")
    async def log_payloads(request: Request, call_next):
        if not settings.a2a_log_payloads:
            return await call_next(request)

        sensitive_method, request_omit_reason = await _payload_request_log_info(
            request,
            settings=settings,
        )
        response = await call_next(request)
        _payload_response_log(
            response,
            path=request.url.path,
            sensitive_method=sensitive_method,
            request_omit_reason=request_omit_reason,
            limit=settings.a2a_log_body_limit,
        )
        return response


def _install_bearer_auth_middleware(
    app: FastAPI,
    *,
    configured_credentials: tuple[StaticAuthCredential, ...],
    advertised_schemes: set[str],
) -> None:
    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in _PUBLIC_AGENT_CARD_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        try:
            auth_scheme, auth_value = auth_header.split(" ", 1)
        except ValueError:
            return _unauthorized_response(advertised_schemes)
        principal = authenticate_static_credential(
            credentials=configured_credentials,
            auth_scheme=auth_scheme,
            auth_value=auth_value.strip(),
        )
        if principal is None:
            return _unauthorized_response(advertised_schemes)
        request.state.authenticated_principal = principal
        request.state.user_identity = principal.identity
        request.state.user_auth_scheme = principal.auth_scheme
        if principal.credential_id:
            request.state.user_credential_id = principal.credential_id

        return await call_next(request)


def _install_http_boundary_middleware(app: FastAPI, *, settings: Settings) -> None:
    """Enforce the inbound Origin/Host boundary (CSRF and DNS rebinding guard).

    Browsers attach stored Basic credentials to every request and send an
    ``Origin`` header, so a cross-origin page could otherwise trigger task
    submission, cancellation, or subscription. Requests carrying an ``Origin``
    header must match the origin derived from ``A2A_PUBLIC_URL`` or an entry in
    ``A2A_ALLOWED_ORIGINS``; requests without an ``Origin`` header (CLI/SDK
    clients) are unaffected.

    When ``A2A_ALLOWED_HOSTS`` is configured, the ``Host`` header is validated
    for every request (exact names or ``*.example.com`` wildcards). Binding to
    a non-loopback address without a host allowlist logs a startup warning
    because the service is then exposed to DNS rebinding.
    """

    allowed_origins = _normalized_origins(settings.a2a_allowed_origins)
    public_origin = _origin_of_url(settings.a2a_public_url)
    if public_origin is not None:
        allowed_origins.add(public_origin)
    else:
        logger.warning(
            "A2A_PUBLIC_URL=%r is not a valid http(s) URL; requests carrying an "
            "Origin header will be rejected unless A2A_ALLOWED_ORIGINS matches",
            settings.a2a_public_url,
        )
    allowed_hosts = tuple(settings.a2a_allowed_hosts or ())
    allowed_host_headers = {entry.strip().lower() for entry in allowed_hosts if entry.strip()}
    enforce_host = bool(allowed_hosts)
    if not enforce_host and not _is_loopback_bind(settings.a2a_host):
        logger.warning(
            "A2A server is bound to non-loopback host=%s without A2A_ALLOWED_HOSTS; "
            "set a Host allowlist to defend against DNS rebinding",
            settings.a2a_host,
        )
    if enforce_host and public_origin is not None:
        public_host = public_origin.split("://", 1)[1]
        if public_host.lower() not in allowed_host_headers and not matches_allowed_host(
            _hostname_from_host_header(public_host),
            allowed_hosts,
        ):
            logger.warning(
                "A2A_PUBLIC_URL host %r is not covered by A2A_ALLOWED_HOSTS; "
                "requests matching the public origin may be rejected on Host",
                public_host,
            )

    @app.middleware("http")
    async def enforce_http_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None:
            normalized_origin = origin.strip().lower().rstrip("/")
            if normalized_origin not in allowed_origins:
                return _boundary_rejection_response("Cross-origin request rejected")

        if enforce_host:
            host = request.headers.get("host")
            hostname = _hostname_from_host_header(host or "")
            host_header_allowed = (host or "").strip().lower() in allowed_host_headers
            if not hostname or not (
                host_header_allowed or matches_allowed_host(hostname, allowed_hosts)
            ):
                return _boundary_rejection_response("Host not allowed")

        return await call_next(request)


def _install_correlation_id_middleware(app: FastAPI) -> None:
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

    # Registration order is significant: Starlette wraps the most recently
    # added middleware outermost, so this mirrors the original single-function
    # registration order exactly.
    _install_protocol_negotiation_middleware(app)
    _install_agent_card_cache_middleware(
        app,
        public_card_etag=public_card_etag,
        extended_card_etag=extended_card_etag,
    )
    _install_rest_payload_shape_guard(app)
    _install_subscribe_task_guard(app, task_store=task_store)
    _install_payload_logging_middleware(app, settings=settings)
    _install_bearer_auth_middleware(
        app,
        configured_credentials=configured_credentials,
        advertised_schemes=advertised_schemes,
    )
    _install_http_boundary_middleware(app, settings=settings)
    _install_correlation_id_middleware(app)
