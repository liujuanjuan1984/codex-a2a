from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any

from codex_a2a.logging_context import bind_correlation_id, get_correlation_id
from codex_a2a.upstream.models import CodexRPCError, _PendingRpcRequest

logger = logging.getLogger("codex_a2a.upstream.client")


class CodexStdioJsonRpcTransport:
    """Own the Codex stdio process and raw JSON-RPC request/response flow."""

    def __init__(
        self,
        *,
        listen: str,
        startup_cli_args: list[str],
        log_payloads: bool,
    ) -> None:
        self._listen = listen
        self._startup_cli_args = list(startup_cli_args)
        self._log_payloads = log_payloads

        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False

        self._init_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

        self._initialized = False
        self._next_request_id = 1
        self._pending_requests: dict[str, _PendingRpcRequest] = {}

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        return self._process

    @process.setter
    def process(self, value: asyncio.subprocess.Process | None) -> None:
        self._process = value

    @property
    def pending_requests(self) -> dict[str, _PendingRpcRequest]:
        return self._pending_requests

    @pending_requests.setter
    def pending_requests(self, value: dict[str, _PendingRpcRequest]) -> None:
        self._pending_requests = value

    async def close(self) -> None:
        self._closed = True
        async with self._state_lock:
            process = self._process
            self._process = None

        for task in (self._stdout_task, self._stderr_task):
            if task:
                task.cancel()
        self._stdout_task = None
        self._stderr_task = None

        self._fail_pending_requests("codex app-server closed")

        if process:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.5)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    async def ensure_started(
        self,
        *,
        resolve_cli_bin: Callable[[], str],
        read_stdout_loop: Callable[[], Coroutine[Any, Any, None]],
        read_stderr_loop: Callable[[], Coroutine[Any, Any, None]],
        initialize_client: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        if self._closed:
            raise RuntimeError("codex client already closed")
        if self._initialized and self._process and self._process.returncode is None:
            return

        async with self._init_lock:
            if self._initialized and self._process and self._process.returncode is None:
                return
            if self._closed:
                raise RuntimeError("codex client already closed")

            cli_args: list[str] = [resolve_cli_bin()]
            cli_args.extend(self._startup_cli_args)
            cli_args.extend(
                [
                    "app-server",
                    "--listen",
                    self._listen,
                ]
            )

            process = await asyncio.create_subprocess_exec(
                *cli_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self._process = process
            self._stdout_task = asyncio.create_task(read_stdout_loop())
            self._stderr_task = asyncio.create_task(read_stderr_loop())

            await initialize_client()
            self._initialized = True

    async def read_stdout_loop(
        self,
        *,
        dispatch_message: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            async for line in self._iter_stream_lines(process.stdout):
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("drop non-json line from codex app-server: %s", raw)
                    continue
                if not isinstance(message, dict):
                    logger.debug(
                        "drop non-object jsonrpc payload from codex app-server: %s",
                        type(message).__name__,
                    )
                    continue
                await dispatch_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive
            logger.exception("codex app-server stdout loop failed")
        finally:
            self._fail_pending_requests("codex app-server stdout closed")

    async def read_stderr_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            async for line in self._iter_stream_lines(process.stderr):
                raw = line.decode("utf-8", errors="replace").rstrip()
                if raw:
                    logger.debug("codex app-server stderr: %s", raw)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive
            logger.exception("codex app-server stderr loop failed")

    async def dispatch_response(self, message: dict[str, Any]) -> bool:
        if "id" not in message or ("result" not in message and "error" not in message):
            return False

        key = str(message["id"])
        pending = self._pending_requests.pop(key, None)
        if not pending:
            return True

        with bind_correlation_id(pending.correlation_id):
            if "error" in message:
                err = message["error"] if isinstance(message["error"], dict) else {}
                code = int(err.get("code", -32000))
                text = str(err.get("message", "unknown codex rpc error"))
                logger.warning(
                    "codex rpc error method=%s request_id=%s code=%s",
                    pending.method,
                    pending.request_id,
                    code,
                )
                pending.future.set_exception(
                    CodexRPCError(code=code, message=text, data=err.get("data"))
                )
            else:
                logger.debug(
                    "codex rpc response method=%s request_id=%s",
                    pending.method,
                    pending.request_id,
                )
                pending.future.set_result(message.get("result"))
        return True

    async def send_json_message(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("codex app-server is not running")
        line = json.dumps(payload, ensure_ascii=False)
        if self._log_payloads:
            logger.debug("codex app-server -> %s", line)
        async with self._write_lock:
            process.stdin.write((line + "\n").encode("utf-8"))
            await process.stdin.drain()

    async def rpc_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        ensure_started: Callable[[], Coroutine[Any, Any, None]] | None = None,
        skip_ensure: bool = False,
        timeout_seconds: float | None = None,
    ) -> Any:
        if not skip_ensure:
            if ensure_started is None:
                raise RuntimeError("codex transport requires an ensure_started callback")
            await ensure_started()
        request_id = str(self._next_request_id)
        self._next_request_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        correlation_id = get_correlation_id()
        self._pending_requests[request_id] = _PendingRpcRequest(
            request_id=request_id,
            method=method,
            future=future,
            correlation_id=correlation_id,
        )
        payload: dict[str, Any] = {"id": int(request_id), "method": method}
        if params is not None:
            payload["params"] = params
        logger.debug("codex rpc request method=%s request_id=%s", method, request_id)
        await self.send_json_message(payload)
        try:
            if timeout_seconds is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            pending = self._pending_requests.pop(request_id, None)
            with bind_correlation_id(correlation_id):
                logger.warning("codex rpc timeout method=%s request_id=%s", method, request_id)
            if pending is not None and not pending.future.done():
                pending.future.cancel()
            raise RuntimeError(f"codex rpc timeout: {method}") from exc

    async def _iter_stream_lines(
        self,
        stream: Any,
        *,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        buffer = bytearray()
        while True:
            chunk = await stream.read(chunk_size)
            if not chunk:
                break
            buffer.extend(chunk)
            while True:
                newline_index = buffer.find(b"\n")
                if newline_index < 0:
                    break
                line = bytes(buffer[:newline_index])
                del buffer[: newline_index + 1]
                yield line
        if buffer:
            yield bytes(buffer)

    def _fail_pending_requests(self, message: str) -> None:
        for pending in self._pending_requests.values():
            if not pending.future.done():
                pending.future.set_exception(RuntimeError(message))
        self._pending_requests.clear()
