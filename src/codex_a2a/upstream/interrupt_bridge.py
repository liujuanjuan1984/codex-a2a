from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from codex_a2a.upstream.interrupts import (
    InterruptRequestBinding,
    InterruptRequestError,
    InterruptRequestTombstone,
    _PendingInterruptRequest,
    build_codex_elicitation_interrupt_properties,
    build_codex_permission_interrupt_properties,
    build_codex_permissions_interrupt_properties,
    build_codex_question_interrupt_properties,
    interrupt_request_status,
)

if TYPE_CHECKING:
    from codex_a2a.server.runtime_state import InterruptRequestRepository


@dataclass(frozen=True)
class _InterruptExecutionContext:
    identity: str | None
    credential_id: str | None
    task_id: str | None
    context_id: str | None


_INTERNAL_INTERRUPT_METHOD_FIELD = "_codexMethod"
_DEFAULT_INTERRUPT_METHODS_BY_TYPE = {
    "permission": "item/commandExecution/requestApproval",
    "question": "item/tool/requestUserInput",
    "permissions": "item/permissions/requestApproval",
    "elicitation": "mcpServer/elicitation/request",
}
_INTERRUPT_PROPERTIES_BUILDERS = {
    "permission": build_codex_permission_interrupt_properties,
    "question": build_codex_question_interrupt_properties,
    "permissions": build_codex_permissions_interrupt_properties,
    "elicitation": build_codex_elicitation_interrupt_properties,
}


class CodexInterruptBridge:
    """Own interrupt request state and upstream server-request semantics."""

    def __init__(
        self,
        *,
        now: Callable[[], float] = time.time,
        interrupt_request_ttl_seconds: int,
        interrupt_request_tombstone_ttl_seconds: int,
        interrupt_request_store: InterruptRequestRepository | None = None,
    ) -> None:
        self._now = now
        self._interrupt_request_ttl_seconds = interrupt_request_ttl_seconds
        self._interrupt_request_tombstone_ttl_seconds = interrupt_request_tombstone_ttl_seconds
        self._interrupt_request_store = interrupt_request_store

        self._pending_server_requests: dict[str, _PendingInterruptRequest] = {}
        self._expired_server_requests: dict[str, InterruptRequestTombstone] = {}
        self._active_interrupt_contexts: dict[str, _InterruptExecutionContext] = {}

    @property
    def pending_server_requests(self) -> dict[str, _PendingInterruptRequest]:
        return self._pending_server_requests

    @property
    def expired_server_requests(self) -> dict[str, InterruptRequestTombstone]:
        return self._expired_server_requests

    @property
    def active_interrupt_contexts(self) -> dict[str, _InterruptExecutionContext]:
        return self._active_interrupt_contexts

    async def restore_persisted_interrupt_requests(self) -> None:
        if self._interrupt_request_store is None:
            return
        restored = await self._interrupt_request_store.load_interrupt_requests()
        for entry in restored:
            self._pending_server_requests[entry.request_id] = _PendingInterruptRequest(
                binding=entry.binding,
                rpc_request_id=entry.rpc_request_id,
                params=entry.params,
            )

    def bind_interrupt_context(
        self,
        *,
        session_id: str,
        identity: str | None,
        credential_id: str | None,
        task_id: str | None,
        context_id: str | None,
    ) -> None:
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            return
        self._active_interrupt_contexts[normalized_session_id] = _InterruptExecutionContext(
            identity=self._optional_string(identity),
            credential_id=self._optional_string(credential_id),
            task_id=self._optional_string(task_id),
            context_id=self._optional_string(context_id),
        )

    def release_interrupt_context(self, *, session_id: str) -> None:
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            return
        self._active_interrupt_contexts.pop(normalized_session_id, None)

    async def handle_server_request(
        self,
        message: dict[str, Any],
        *,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params")
        if not isinstance(method, str):
            return
        if params is None:
            params = {}
        if not isinstance(params, dict):
            params = {}

        request_key = str(request_id)
        session_id = str(params.get("threadId") or params.get("conversationId") or "").strip()

        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }:
            await self._register_interrupt_request(
                request_id=request_id,
                request_key=request_key,
                method=method,
                params=params,
                interrupt_type="permission",
                asked_event_type="permission.asked",
                session_id=session_id,
                properties_builder=build_codex_permission_interrupt_properties,
                enqueue_stream_event=enqueue_stream_event,
            )
            return

        if method == "item/tool/requestUserInput":
            await self._register_interrupt_request(
                request_id=request_id,
                request_key=request_key,
                method=method,
                params=params,
                interrupt_type="question",
                asked_event_type="question.asked",
                session_id=session_id,
                properties_builder=build_codex_question_interrupt_properties,
                enqueue_stream_event=enqueue_stream_event,
            )
            return

        if method == "item/permissions/requestApproval":
            await self._register_interrupt_request(
                request_id=request_id,
                request_key=request_key,
                method=method,
                params=params,
                interrupt_type="permissions",
                asked_event_type="permissions.asked",
                session_id=session_id,
                properties_builder=build_codex_permissions_interrupt_properties,
                enqueue_stream_event=enqueue_stream_event,
            )
            return

        if method == "mcpServer/elicitation/request":
            await self._register_interrupt_request(
                request_id=request_id,
                request_key=request_key,
                method=method,
                params=params,
                interrupt_type="elicitation",
                asked_event_type="elicitation.asked",
                session_id=session_id,
                properties_builder=build_codex_elicitation_interrupt_properties,
                enqueue_stream_event=enqueue_stream_event,
            )
            return

        await send_json_message(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unsupported server request method: {method}",
                },
            }
        )

    def interrupt_request_status(
        self,
        binding: InterruptRequestBinding,
    ) -> str:
        return interrupt_request_status(
            binding,
            interrupt_request_ttl_seconds=self._interrupt_request_ttl_seconds,
        )

    async def resolve_interrupt_request(
        self, request_id: str
    ) -> tuple[str, InterruptRequestBinding | None]:
        request_key = request_id.strip()
        if not request_key:
            return "missing", None
        self._purge_expired_interrupt_tombstones()
        pending = self._pending_server_requests.get(request_key)
        if pending is not None:
            status = self.interrupt_request_status(pending.binding)
            if status == "expired":
                self._remember_interrupt_tombstone(request_key)
                if self._interrupt_request_store is not None:
                    await self._interrupt_request_store.expire_interrupt_request(
                        request_id=request_key
                    )
                return "expired", None
            return status, pending.binding
        if request_key in self._expired_server_requests:
            return "expired", None
        if self._interrupt_request_store is None:
            return "missing", None
        status, persisted = await self._interrupt_request_store.resolve_interrupt_request(
            request_id=request_key
        )
        if status == "active" and persisted is not None:
            pending = _PendingInterruptRequest(
                binding=persisted.binding,
                rpc_request_id=persisted.rpc_request_id,
                params=persisted.params,
            )
            self._pending_server_requests[request_key] = pending
            return "active", pending.binding
        if status == "expired":
            self._remember_interrupt_tombstone(request_key)
            return "expired", None
        return "missing", None

    async def discard_interrupt_request(self, request_id: str) -> None:
        request_key = request_id.strip()
        self._pending_server_requests.pop(request_key, None)
        self._expired_server_requests.pop(request_key, None)
        if self._interrupt_request_store is not None:
            await self._interrupt_request_store.delete_interrupt_request(request_id=request_key)

    async def list_interrupt_requests(
        self,
        *,
        identity: str | None,
        credential_id: str | None,
        interrupt_type: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_identity = self._optional_string(identity)
        normalized_credential_id = self._optional_string(credential_id)
        if normalized_identity is None and normalized_credential_id is None:
            return []

        items: list[dict[str, Any]] = []
        for request_id, pending in list(self._pending_server_requests.items()):
            status = self.interrupt_request_status(pending.binding)
            if status == "expired":
                self._remember_interrupt_tombstone(request_id)
                if self._interrupt_request_store is not None:
                    await self._interrupt_request_store.expire_interrupt_request(
                        request_id=request_id
                    )
                continue
            if interrupt_type is not None and pending.binding.interrupt_type != interrupt_type:
                continue
            if not self._binding_visible_to_caller(
                pending.binding,
                identity=normalized_identity,
                credential_id=normalized_credential_id,
            ):
                continue
            items.append(self._build_interrupt_recovery_item(pending))

        items.sort(key=lambda item: (item["created_at"], item["request_id"]))
        return items

    async def permission_reply(
        self,
        request_id: str,
        *,
        reply: str,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        normalized = (reply or "").strip().lower()
        pending = await self._require_pending_interrupt_request(
            request_id,
            expected_interrupt_type="permission",
        )
        decision = "decline"
        if normalized == "once":
            decision = "accept"
        elif normalized == "always":
            decision = "acceptForSession"
        elif normalized in {"reject", "deny"}:
            decision = "decline"

        await self._reply_to_server_request(
            request_id=request_id,
            pending=pending,
            result={"decision": decision},
            resolved_event_type="permission.replied",
            send_json_message=send_json_message,
            enqueue_stream_event=enqueue_stream_event,
        )
        return True

    async def question_reply(
        self,
        request_id: str,
        *,
        answers: list[list[str]],
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        pending = await self._require_pending_interrupt_request(
            request_id,
            expected_interrupt_type="question",
        )
        questions = pending.params.get("questions")
        answer_map: dict[str, dict[str, list[str]]] = {}
        if isinstance(questions, list):
            for index, q in enumerate(questions):
                if not isinstance(q, dict):
                    continue
                qid = q.get("id")
                if not isinstance(qid, str) or not qid:
                    continue
                selected = answers[index] if index < len(answers) else []
                selected = [v for v in selected if isinstance(v, str)]
                answer_map[qid] = {"answers": selected}
        await self._reply_to_server_request(
            request_id=request_id,
            pending=pending,
            result={"answers": answer_map},
            resolved_event_type="question.replied",
            send_json_message=send_json_message,
            enqueue_stream_event=enqueue_stream_event,
        )
        return True

    async def question_reject(
        self,
        request_id: str,
        *,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        pending = await self._require_pending_interrupt_request(
            request_id,
            expected_interrupt_type="question",
        )
        await send_json_message({"id": pending.rpc_request_id, "result": {"answers": {}}})
        await enqueue_stream_event(
            {
                "type": "question.rejected",
                "properties": {
                    "id": request_id,
                    "requestID": request_id,
                    "sessionID": pending.binding.session_id,
                },
            }
        )
        await self.discard_interrupt_request(request_id)
        return True

    async def permissions_reply(
        self,
        request_id: str,
        *,
        permissions: Mapping[str, Any],
        scope: str | None,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        pending = await self._require_pending_interrupt_request(
            request_id,
            expected_interrupt_type="permissions",
        )
        result: dict[str, Any] = {"permissions": dict(permissions)}
        if scope is not None:
            result["scope"] = scope
        await self._reply_to_server_request(
            request_id=request_id,
            pending=pending,
            result=result,
            resolved_event_type="permissions.replied",
            send_json_message=send_json_message,
            enqueue_stream_event=enqueue_stream_event,
        )
        return True

    async def elicitation_reply(
        self,
        request_id: str,
        *,
        action: str,
        content: Any,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        pending = await self._require_pending_interrupt_request(
            request_id,
            expected_interrupt_type="elicitation",
        )
        result: dict[str, Any] = {"action": action, "content": content}
        await self._reply_to_server_request(
            request_id=request_id,
            pending=pending,
            result=result,
            resolved_event_type=(
                "elicitation.replied" if action == "accept" else "elicitation.rejected"
            ),
            send_json_message=send_json_message,
            enqueue_stream_event=enqueue_stream_event,
        )
        return True

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _binding_visible_to_caller(
        self,
        binding: InterruptRequestBinding,
        *,
        identity: str | None,
        credential_id: str | None,
    ) -> bool:
        binding_identity = self._optional_string(binding.identity)
        binding_credential_id = self._optional_string(binding.credential_id)
        if binding_identity is None and binding_credential_id is None:
            return False
        if binding_identity is not None and binding_identity != identity:
            return False
        if binding_credential_id is not None and binding_credential_id != credential_id:
            return False
        return True

    def _strip_internal_interrupt_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if _INTERNAL_INTERRUPT_METHOD_FIELD not in params:
            return dict(params)
        sanitized = dict(params)
        sanitized.pop(_INTERNAL_INTERRUPT_METHOD_FIELD, None)
        return sanitized

    def _build_interrupt_recovery_properties(
        self,
        pending: _PendingInterruptRequest,
    ) -> dict[str, Any]:
        builder = _INTERRUPT_PROPERTIES_BUILDERS.get(pending.binding.interrupt_type)
        if builder is None:
            return {
                "id": pending.binding.request_id,
                "sessionID": pending.binding.session_id,
            }
        params = self._strip_internal_interrupt_params(pending.params)
        method = self._optional_string(pending.params.get(_INTERNAL_INTERRUPT_METHOD_FIELD)) or (
            _DEFAULT_INTERRUPT_METHODS_BY_TYPE.get(pending.binding.interrupt_type)
            or pending.binding.interrupt_type
        )
        return builder(
            request_key=pending.binding.request_id,
            session_id=pending.binding.session_id,
            method=method,
            params=params,
        )

    def _build_interrupt_recovery_item(
        self,
        pending: _PendingInterruptRequest,
    ) -> dict[str, Any]:
        binding = pending.binding
        return {
            "request_id": binding.request_id,
            "interrupt_type": binding.interrupt_type,
            "session_id": binding.session_id,
            "task_id": binding.task_id,
            "context_id": binding.context_id,
            "created_at": binding.created_at,
            "expires_at": binding.expires_at,
            "properties": self._build_interrupt_recovery_properties(pending),
        }

    def _resolve_interrupt_context(
        self,
        *,
        session_id: str,
        params: dict[str, Any],
    ) -> _InterruptExecutionContext:
        active_context = self._active_interrupt_contexts.get(session_id)
        return _InterruptExecutionContext(
            identity=(
                self._optional_string(params.get("identity"))
                or self._optional_string(params.get("userIdentity"))
                or (active_context.identity if active_context is not None else None)
            ),
            credential_id=(
                self._optional_string(params.get("credential_id"))
                or self._optional_string(params.get("credentialId"))
                or (active_context.credential_id if active_context is not None else None)
            ),
            task_id=(
                self._optional_string(params.get("task_id"))
                or self._optional_string(params.get("taskId"))
                or (active_context.task_id if active_context is not None else None)
            ),
            context_id=(
                self._optional_string(params.get("context_id"))
                or self._optional_string(params.get("contextId"))
                or (active_context.context_id if active_context is not None else None)
            ),
        )

    def _purge_expired_interrupt_tombstones(self) -> None:
        now = self._now()
        expired = [
            request_id
            for request_id, tombstone in self._expired_server_requests.items()
            if tombstone.expires_at <= now
        ]
        for request_id in expired:
            self._expired_server_requests.pop(request_id, None)

    def _remember_interrupt_tombstone(self, request_id: str) -> None:
        ttl_seconds = self._interrupt_request_tombstone_ttl_seconds
        self._pending_server_requests.pop(request_id, None)
        if ttl_seconds <= 0:
            self._expired_server_requests.pop(request_id, None)
            return
        self._expired_server_requests[request_id] = InterruptRequestTombstone(
            request_id=request_id,
            expires_at=self._now() + ttl_seconds,
        )

    async def _require_pending_interrupt_request(
        self,
        request_id: str,
        *,
        expected_interrupt_type: str,
    ) -> _PendingInterruptRequest:
        request_key = request_id.strip()
        status, binding = await self.resolve_interrupt_request(request_key)
        if status == "missing":
            raise InterruptRequestError(
                error_type="INTERRUPT_REQUEST_NOT_FOUND",
                request_id=request_key,
            )
        if status == "expired" or binding is None:
            raise InterruptRequestError(
                error_type="INTERRUPT_REQUEST_EXPIRED",
                request_id=request_key,
            )
        if binding.interrupt_type != expected_interrupt_type:
            raise InterruptRequestError(
                error_type="INTERRUPT_TYPE_MISMATCH",
                request_id=request_key,
                expected_interrupt_type=expected_interrupt_type,
                actual_interrupt_type=binding.interrupt_type,
            )
        pending = self._pending_server_requests.get(request_key)
        if pending is None:
            raise InterruptRequestError(
                error_type="INTERRUPT_REQUEST_NOT_FOUND",
                request_id=request_key,
            )
        return pending

    async def _register_interrupt_request(
        self,
        *,
        request_id: Any,
        request_key: str,
        method: str,
        params: dict[str, Any],
        interrupt_type: str,
        asked_event_type: str,
        session_id: str,
        properties_builder: Callable[..., dict[str, Any]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        interrupt_context = self._resolve_interrupt_context(session_id=session_id, params=params)
        rpc_request_id = request_id if isinstance(request_id, str | int) else request_key
        created_at = self._now()
        stored_params = {_INTERNAL_INTERRUPT_METHOD_FIELD: method, **params}
        self._pending_server_requests[request_key] = _PendingInterruptRequest(
            binding=InterruptRequestBinding(
                request_id=request_key,
                interrupt_type=interrupt_type,
                session_id=session_id,
                created_at=created_at,
                expires_at=created_at + float(self._interrupt_request_ttl_seconds),
                identity=interrupt_context.identity,
                credential_id=interrupt_context.credential_id,
                task_id=interrupt_context.task_id,
                context_id=interrupt_context.context_id,
            ),
            rpc_request_id=rpc_request_id,
            params=stored_params,
        )
        self._expired_server_requests.pop(request_key, None)
        if self._interrupt_request_store is not None:
            binding = self._pending_server_requests[request_key].binding
            await self._interrupt_request_store.save_interrupt_request(
                request_id=request_key,
                interrupt_type=binding.interrupt_type,
                session_id=binding.session_id,
                identity=binding.identity,
                credential_id=binding.credential_id,
                task_id=binding.task_id,
                context_id=binding.context_id,
                created_at=binding.created_at,
                expires_at=binding.expires_at or binding.created_at,
                rpc_request_id=rpc_request_id,
                params=stored_params,
            )
        await enqueue_stream_event(
            {
                "type": asked_event_type,
                "properties": properties_builder(
                    request_key=request_key,
                    session_id=session_id,
                    method=method,
                    params=params,
                ),
            }
        )

    async def _reply_to_server_request(
        self,
        *,
        request_id: str,
        pending: _PendingInterruptRequest,
        result: dict[str, Any],
        resolved_event_type: str,
        send_json_message: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_stream_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await send_json_message({"id": pending.rpc_request_id, "result": result})
        await enqueue_stream_event(
            {
                "type": resolved_event_type,
                "properties": {
                    "id": request_id,
                    "requestID": request_id,
                    "sessionID": pending.binding.session_id,
                },
            }
        )
        await self.discard_interrupt_request(request_id)
