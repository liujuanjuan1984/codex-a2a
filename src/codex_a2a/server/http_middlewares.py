from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from urllib.parse import unquote

from a2a.server.tasks.task_store import TaskStore
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response, StreamingResponse

from codex_a2a.config import Settings
from codex_a2a.logging_context import (
    CORRELATION_ID_HEADER,
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
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
_REST_MESSAGE_PATHS = {
    "/v1/message:send",
    "/v1/message:stream",
}
PUBLIC_AGENT_CARD_CACHE_CONTROL = "public, max-age=300"
AUTHENTICATED_EXTENDED_CARD_CACHE_CONTROL = "private, max-age=300"


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

    def _unauthorized_response() -> JSONResponse:
        return JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

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
                },
            )

        response = await call_next(request)
        if response.status_code != 200:
            return response

        if is_public_card:
            response.headers["ETag"] = public_card_etag
            response.headers["Cache-Control"] = PUBLIC_AGENT_CARD_CACHE_CONTROL
            return response

        response.headers["ETag"] = extended_card_etag
        response.headers["Cache-Control"] = AUTHENTICATED_EXTENDED_CARD_CACHE_CONTROL
        response.headers["Vary"] = _merge_vary(
            response.headers.get("Vary", ""),
            "Authorization",
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
        if not auth_header.lower().startswith("bearer "):
            return _unauthorized_response()
        provided = auth_header.split(" ", 1)[1].strip()
        if not secrets.compare_digest(provided, settings.a2a_bearer_token):
            return _unauthorized_response()
        request.state.user_identity = f"bearer:{hashlib.sha256(provided.encode()).hexdigest()[:12]}"

        return await call_next(request)

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        correlation_id = resolve_correlation_id(request.headers.get("x-request-id"))
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        started_at = time.perf_counter()
        path = request.url.path
        logger.info("A2A request started method=%s path=%s", request.method, path)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            logger.info(
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
