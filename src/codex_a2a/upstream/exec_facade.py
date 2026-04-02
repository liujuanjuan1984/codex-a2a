from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from codex_a2a.upstream.request_mapping import build_interactive_exec_params


class CodexExecFacade:
    """Own interactive exec RPC mappings while keeping the client API stable."""

    def __init__(
        self,
        *,
        workspace_root: str | None,
        rpc_request: Callable[..., Awaitable[Any]],
    ) -> None:
        self._workspace_root = workspace_root
        self._rpc_request = rpc_request

    async def exec_start(
        self,
        request: dict[str, Any],
        *,
        directory: str | None = None,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        result = await self._rpc_request(
            "command/exec",
            build_interactive_exec_params(
                command_text=str(request["command"]).strip(),
                arguments=request.get("arguments"),
                process_id=str(request["processId"]).strip(),
                directory=directory,
                default_workspace_root=self._workspace_root,
                tty=bool(request.get("tty", True)),
                rows=request.get("rows"),
                cols=request.get("cols"),
                output_bytes_cap=request.get("outputBytesCap"),
                disable_output_cap=request.get("disableOutputCap"),
                timeout_ms=request.get("timeoutMs"),
                disable_timeout=request.get("disableTimeout"),
            ),
            timeout_override=timeout_seconds,
        )
        if not isinstance(result, dict):
            raise RuntimeError("codex command/exec response missing result object")
        return result

    async def exec_write(
        self,
        *,
        process_id: str,
        delta_base64: str | None = None,
        close_stdin: bool | None = None,
    ) -> None:
        params: dict[str, Any] = {"processId": process_id}
        if delta_base64 is not None:
            params["deltaBase64"] = delta_base64
        if close_stdin is not None:
            params["closeStdin"] = close_stdin
        await self._rpc_request("command/exec/write", params)

    async def exec_resize(
        self,
        *,
        process_id: str,
        rows: int,
        cols: int,
    ) -> None:
        await self._rpc_request(
            "command/exec/resize",
            {"processId": process_id, "size": {"rows": rows, "cols": cols}},
        )

    async def exec_terminate(
        self,
        *,
        process_id: str,
    ) -> None:
        await self._rpc_request("command/exec/terminate", {"processId": process_id})
