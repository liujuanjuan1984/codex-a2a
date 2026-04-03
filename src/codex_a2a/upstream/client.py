from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any

from codex_a2a import __version__
from codex_a2a.config import Settings
from codex_a2a.execution.request_overrides import RequestExecutionOptions
from codex_a2a.logging_context import (
    install_log_record_factory,
)
from codex_a2a.upstream.conversation_facade import CodexConversationFacade
from codex_a2a.upstream.exec_facade import CodexExecFacade
from codex_a2a.upstream.interrupt_bridge import CodexInterruptBridge
from codex_a2a.upstream.interrupts import (
    INTERRUPT_REQUEST_TOMBSTONE_TTL_SECONDS,
    InterruptRequestBinding,
    _PendingInterruptRequest,
)
from codex_a2a.upstream.models import (
    CodexMessage,
    CodexStartupPrerequisiteError,
    _PendingRpcRequest,
    _TurnTracker,
)
from codex_a2a.upstream.startup import (
    build_cli_config_args,
    build_startup_config_overrides,
    resolve_cli_bin,
)
from codex_a2a.upstream.stream_bridge import CodexStreamEventBridge
from codex_a2a.upstream.transport import CodexStdioJsonRpcTransport

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from codex_a2a.server.runtime_state import InterruptRequestRepository


class _UnsetType:
    pass


_UNSET = _UnsetType()
_DEFAULT_CLIENT_NAME = "codex_a2a"
_DEFAULT_CLIENT_TITLE = "Codex A2A"
_EVENT_QUEUE_MAXSIZE = 2048


class CodexClient:
    """Codex app-server client adapter (stdio JSON-RPC)."""

    def __init__(
        self,
        settings: Settings,
        *,
        interrupt_request_store: InterruptRequestRepository | None = None,
    ) -> None:
        install_log_record_factory()
        self._settings = settings
        self._workspace_root = settings.codex_workspace_root
        self._model_id = settings.codex_model_id
        self._stream_timeout = settings.codex_timeout_stream
        self._request_timeout = settings.codex_timeout
        self._cli_bin = settings.codex_cli_bin
        self._listen = settings.codex_app_server_listen
        self._startup_config_overrides = build_startup_config_overrides(settings)
        self._interrupt_request_ttl_seconds = settings.a2a_interrupt_request_ttl_seconds
        self._interrupt_request_tombstone_ttl_seconds = int(INTERRUPT_REQUEST_TOMBSTONE_TTL_SECONDS)
        self._log_payloads = settings.a2a_log_payloads
        self._interrupt_request_store = interrupt_request_store

        self._transport = CodexStdioJsonRpcTransport(
            listen=self._listen,
            startup_cli_args=build_cli_config_args(self._startup_config_overrides),
            log_payloads=self._log_payloads,
        )
        self._stream_bridge = CodexStreamEventBridge(event_queue_maxsize=_EVENT_QUEUE_MAXSIZE)
        self._conversation_facade = CodexConversationFacade(
            workspace_root=self._workspace_root,
            model_id=self._model_id,
            rpc_request=lambda method, params=None, **kwargs: self._rpc_request(
                method,
                params,
                **kwargs,
            ),
            get_or_create_tracker=lambda thread_id, turn_id: self._get_or_create_tracker(
                thread_id,
                turn_id,
            ),
            turn_trackers=self._turn_trackers,
        )
        self._exec_facade = CodexExecFacade(
            workspace_root=self._workspace_root,
            rpc_request=lambda method, params=None, **kwargs: self._rpc_request(
                method,
                params,
                **kwargs,
            ),
        )
        self._interrupt_bridge = CodexInterruptBridge(
            now=lambda: time.time(),
            interrupt_request_ttl_seconds=self._interrupt_request_ttl_seconds,
            interrupt_request_tombstone_ttl_seconds=self._interrupt_request_tombstone_ttl_seconds,
            interrupt_request_store=interrupt_request_store,
        )

    async def restore_persisted_interrupt_requests(self) -> None:
        await self._interrupt_bridge.restore_persisted_interrupt_requests()

    @property
    def _process(self) -> asyncio.subprocess.Process | None:
        return self._transport.process

    @_process.setter
    def _process(self, value: asyncio.subprocess.Process | None) -> None:
        self._transport.process = value

    @property
    def _pending_requests(self) -> dict[str, _PendingRpcRequest]:
        return self._transport.pending_requests

    @_pending_requests.setter
    def _pending_requests(self, value: dict[str, _PendingRpcRequest]) -> None:
        self._transport.pending_requests = value

    @property
    def _pending_server_requests(self) -> dict[str, _PendingInterruptRequest]:
        return self._interrupt_bridge.pending_server_requests

    @property
    def _expired_server_requests(self) -> dict[str, Any]:
        return self._interrupt_bridge.expired_server_requests

    @property
    def _active_interrupt_contexts(self) -> dict[str, Any]:
        return self._interrupt_bridge.active_interrupt_contexts

    @property
    def _event_subscribers(self) -> set[asyncio.Queue[dict[str, Any]]]:
        return self._stream_bridge.event_subscribers

    @property
    def _turn_trackers(self) -> dict[tuple[str, str], _TurnTracker]:
        return self._stream_bridge.turn_trackers

    def bind_interrupt_context(
        self,
        *,
        session_id: str,
        identity: str | None,
        task_id: str | None,
        context_id: str | None,
    ) -> None:
        self._interrupt_bridge.bind_interrupt_context(
            session_id=session_id,
            identity=identity,
            task_id=task_id,
            context_id=context_id,
        )

    def release_interrupt_context(self, *, session_id: str) -> None:
        self._interrupt_bridge.release_interrupt_context(session_id=session_id)

    async def close(self) -> None:
        await self._transport.close()

    @property
    def stream_timeout(self) -> float | None:
        return self._stream_timeout

    @property
    def directory(self) -> str | None:
        return self._workspace_root

    @property
    def settings(self) -> Settings:
        return self._settings

    def _resolve_timeout_seconds(
        self,
        *,
        timeout_override: float | None | _UnsetType,
    ) -> float | None:
        if isinstance(timeout_override, _UnsetType):
            return self._request_timeout
        if timeout_override is None:
            return None
        timeout_seconds = float(timeout_override)
        if timeout_seconds <= 0:
            return self._request_timeout
        return timeout_seconds

    def _query_params(self, directory: str | None = None) -> dict[str, str]:
        d = directory or self._workspace_root
        if not d:
            return {}
        return {"directory": d}

    def _merge_params(
        self, extra: dict[str, Any] | None, *, directory: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = dict(self._query_params(directory=directory))
        if not extra:
            return params
        for key, value in extra.items():
            if value is None:
                continue
            if key == "directory":
                continue
            params[key] = value if isinstance(value, str) else str(value)
        return params

    def _resolve_cli_bin(self) -> str:
        return resolve_cli_bin(self._cli_bin)

    async def startup_preflight(self) -> None:
        try:
            await self._ensure_started()
        except CodexStartupPrerequisiteError:
            raise
        except FileNotFoundError as exc:
            raise CodexStartupPrerequisiteError(
                "Codex prerequisite not satisfied: failed to execute the "
                "configured Codex CLI. Verify that Codex is installed and "
                "CODEX_CLI_BIN points to a valid executable."
            ) from exc
        except Exception as exc:
            raise CodexStartupPrerequisiteError(
                "Codex prerequisite not satisfied: failed to start or initialize "
                "`codex app-server`. Verify that Codex itself is usable and "
                "that its provider/auth configuration is valid before "
                "starting codex-a2a."
            ) from exc

    async def _ensure_started(self) -> None:
        async def initialize_client() -> None:
            init_result = await self._rpc_request(
                "initialize",
                {
                    "clientInfo": {
                        "name": _DEFAULT_CLIENT_NAME,
                        "title": _DEFAULT_CLIENT_TITLE,
                        "version": __version__,
                    },
                    "capabilities": {
                        "experimentalApi": True,
                    },
                },
                _skip_ensure=True,
            )
            if self._log_payloads:
                logger.debug("codex initialize result=%s", init_result)
            await self._send_json_message({"method": "initialized", "params": {}})

        await self._transport.ensure_started(
            resolve_cli_bin=self._resolve_cli_bin,
            read_stdout_loop=self._read_stdout_loop,
            read_stderr_loop=self._read_stderr_loop,
            initialize_client=initialize_client,
        )

    async def _read_stdout_loop(self) -> None:
        await self._transport.read_stdout_loop(dispatch_message=self._dispatch_message)

    async def _read_stderr_loop(self) -> None:
        await self._transport.read_stderr_loop()

    async def _dispatch_message(self, message: dict[str, Any]) -> None:
        if await self._transport.dispatch_response(message):
            return

        # 2) Server-initiated request (contains id + method).
        if "id" in message and "method" in message:
            await self._handle_server_request(message)
            return

        # 3) Server notification.
        if "method" in message:
            await self._handle_notification(message)

    async def _send_json_message(self, payload: dict[str, Any]) -> None:
        await self._transport.send_json_message(payload)

    async def _rpc_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        _skip_ensure: bool = False,
        timeout_override: float | None | _UnsetType = _UNSET,
    ) -> Any:
        timeout_seconds = self._resolve_timeout_seconds(timeout_override=timeout_override)
        return await self._transport.rpc_request(
            method,
            params,
            ensure_started=self._ensure_started,
            skip_ensure=_skip_ensure,
            timeout_seconds=timeout_seconds,
        )

    async def _enqueue_stream_event(self, event: dict[str, Any]) -> None:
        await self._stream_bridge.enqueue_stream_event(event)

    def _get_or_create_tracker(self, thread_id: str, turn_id: str) -> _TurnTracker:
        return self._stream_bridge.get_or_create_tracker(thread_id, turn_id)

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        await self._stream_bridge.handle_notification(
            message,
            enqueue_stream_event=self._enqueue_stream_event,
            get_or_create_tracker=self._get_or_create_tracker,
        )

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        await self._interrupt_bridge.handle_server_request(
            message,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )

    async def stream_events(
        self, stop_event: asyncio.Event | None = None, *, directory: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        del directory
        await self._ensure_started()
        async for event in self._stream_bridge.stream_events(stop_event=stop_event):
            yield event

    async def create_session(
        self,
        title: str | None = None,
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> str:
        return await self._conversation_facade.create_session(
            title=title,
            directory=directory,
            execution_options=execution_options,
        )

    async def list_skills(self, *, params: dict[str, Any] | None = None) -> Any:
        return await self._rpc_request("skills/list", self._merge_params(params))

    async def list_apps(self, *, params: dict[str, Any] | None = None) -> Any:
        return await self._rpc_request("app/list", self._merge_params(params))

    async def list_plugins(self, *, params: dict[str, Any] | None = None) -> Any:
        return await self._rpc_request("plugin/list", self._merge_params(params))

    async def read_plugin(self, *, params: dict[str, Any] | None = None) -> Any:
        return await self._rpc_request("plugin/read", self._merge_params(params))

    async def list_sessions(self, *, params: dict[str, Any] | None = None) -> Any:
        return await self._conversation_facade.list_sessions(query=self._merge_params(params))

    async def thread_fork(self, thread_id: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._conversation_facade.thread_fork(thread_id, params=params)

    async def thread_archive(self, thread_id: str) -> None:
        await self._conversation_facade.thread_archive(thread_id)

    async def thread_unarchive(self, thread_id: str) -> Any:
        return await self._conversation_facade.thread_unarchive(thread_id)

    async def thread_metadata_update(
        self,
        thread_id: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._conversation_facade.thread_metadata_update(
            thread_id,
            params=params,
        )

    async def list_messages(self, session_id: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._conversation_facade.list_messages(
            session_id,
            query=self._merge_params(params),
        )

    async def send_message(
        self,
        session_id: str,
        text: str,
        *,
        input_items: list[dict[str, Any]] | None = None,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
        timeout_override: float | None | _UnsetType = _UNSET,
    ) -> CodexMessage:
        return await self._conversation_facade.send_message(
            session_id,
            text,
            input_items=input_items,
            directory=directory,
            execution_options=execution_options,
            timeout_seconds=self._resolve_timeout_seconds(timeout_override=timeout_override),
        )

    async def session_prompt_async(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> dict[str, Any]:
        return await self._conversation_facade.session_prompt_async(
            session_id,
            request,
            directory=directory,
            execution_options=execution_options,
        )

    async def session_command(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        execution_options: RequestExecutionOptions | None = None,
    ) -> CodexMessage:
        return await self._conversation_facade.session_command(
            session_id,
            request,
            directory=directory,
            execution_options=execution_options,
            timeout_seconds=self._request_timeout,
        )

    async def session_shell(
        self,
        session_id: str,
        request: dict[str, Any],
        *,
        directory: str | None = None,
    ) -> dict[str, Any]:
        return await self._conversation_facade.session_shell(
            session_id,
            request,
            directory=directory,
        )

    async def exec_start(
        self,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        timeout_override: float | None | _UnsetType = _UNSET,
    ) -> dict[str, Any]:
        return await self._exec_facade.exec_start(
            request,
            directory=directory,
            timeout_seconds=self._resolve_timeout_seconds(timeout_override=timeout_override),
        )

    async def exec_write(
        self,
        *,
        process_id: str,
        delta_base64: str | None = None,
        close_stdin: bool | None = None,
    ) -> None:
        await self._exec_facade.exec_write(
            process_id=process_id,
            delta_base64=delta_base64,
            close_stdin=close_stdin,
        )

    async def exec_resize(
        self,
        *,
        process_id: str,
        rows: int,
        cols: int,
    ) -> None:
        await self._exec_facade.exec_resize(
            process_id=process_id,
            rows=rows,
            cols=cols,
        )

    async def exec_terminate(
        self,
        *,
        process_id: str,
    ) -> None:
        await self._exec_facade.exec_terminate(process_id=process_id)

    async def resolve_interrupt_request(
        self, request_id: str
    ) -> tuple[str, InterruptRequestBinding | None]:
        return await self._interrupt_bridge.resolve_interrupt_request(request_id)

    async def discard_interrupt_request(self, request_id: str) -> None:
        await self._interrupt_bridge.discard_interrupt_request(request_id)

    async def permission_reply(
        self,
        request_id: str,
        *,
        reply: str,
        message: str | None = None,
        directory: str | None = None,
    ) -> bool:
        del message, directory
        return await self._interrupt_bridge.permission_reply(
            request_id,
            reply=reply,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )

    async def question_reply(
        self,
        request_id: str,
        *,
        answers: list[list[str]],
        directory: str | None = None,
    ) -> bool:
        del directory
        return await self._interrupt_bridge.question_reply(
            request_id,
            answers=answers,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )

    async def question_reject(
        self,
        request_id: str,
        *,
        directory: str | None = None,
    ) -> bool:
        del directory
        return await self._interrupt_bridge.question_reject(
            request_id,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )

    async def permissions_reply(
        self,
        request_id: str,
        *,
        permissions: Mapping[str, Any],
        scope: str | None = None,
        directory: str | None = None,
    ) -> bool:
        del directory
        return await self._interrupt_bridge.permissions_reply(
            request_id,
            permissions=permissions,
            scope=scope,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )

    async def elicitation_reply(
        self,
        request_id: str,
        *,
        action: str,
        content: Any = None,
        directory: str | None = None,
    ) -> bool:
        del directory
        return await self._interrupt_bridge.elicitation_reply(
            request_id,
            action=action,
            content=content,
            send_json_message=self._send_json_message,
            enqueue_stream_event=self._enqueue_stream_event,
        )
