#!/usr/bin/env python3
"""Drive one real Codex app-server turn through an isolated local model provider."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from codex_a2a.config import Settings
from codex_a2a.upstream.client import CodexClient

_PROMPT = "Reply with the configured smoke response."
_RESPONSE_TEXT = "codex-a2a-live-smoke-ok"


def _sse_body() -> bytes:
    events = [
        {"type": "response.created", "response": {"id": "resp-codex-a2a-smoke"}},
        {
            "type": "response.output_item.added",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": "msg-codex-a2a-smoke",
                "content": [{"type": "output_text", "text": ""}],
            },
        },
        {"type": "response.output_text.delta", "delta": _RESPONSE_TEXT},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": "msg-codex-a2a-smoke",
                "content": [{"type": "output_text", "text": _RESPONSE_TEXT}],
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp-codex-a2a-smoke",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": None,
                    "output_tokens": 1,
                    "output_tokens_details": None,
                    "total_tokens": 2,
                },
            },
        },
    ]
    chunks = [f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events]
    return "".join(chunks).encode()


class _SmokeResponsesServer(ThreadingHTTPServer):
    requests: list[dict[str, Any]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmokeResponsesHandler)
        self.requests = []

    @property
    def base_url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}/v1"


class _SmokeResponsesHandler(BaseHTTPRequestHandler):
    server: _SmokeResponsesServer

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.endswith("/models"):
            self.send_error(404, f"unexpected GET {self.path}")
            return
        self._send_json(
            {
                "object": "list",
                "data": [
                    {
                        "id": "codex-a2a-smoke-model",
                        "object": "model",
                        "created": 0,
                        "owned_by": "codex-a2a",
                    }
                ],
            }
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        if not self.path.endswith("/responses"):
            self.send_error(404, f"unexpected POST {self.path}")
            return
        payload = json.loads(body)
        if not isinstance(payload, dict):
            self.send_error(400, "response request must be an object")
            return
        self.server.requests.append(payload)
        response = _sse_body()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _write_codex_wrapper(path: Path, *, codex_bin: str, provider_url: str) -> None:
    config_args = [
        "-c",
        'model="codex-a2a-smoke-model"',
        "-c",
        'model_provider="codex_a2a_smoke"',
        "-c",
        'model_providers.codex_a2a_smoke.name="Codex A2A smoke provider"',
        "-c",
        f'model_providers.codex_a2a_smoke.base_url="{provider_url}"',
        "-c",
        'model_providers.codex_a2a_smoke.wire_api="responses"',
        "-c",
        "model_providers.codex_a2a_smoke.request_max_retries=0",
        "-c",
        "model_providers.codex_a2a_smoke.stream_max_retries=0",
        "-c",
        'approval_policy="never"',
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        "features.plugins=false",
    ]
    wrapper = (
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"codex_bin = {codex_bin!r}\n"
        f"config_args = {config_args!r}\n"
        'os.environ["CODEX_APP_SERVER_DISABLE_MANAGED_CONFIG"] = "1"\n'
        "os.execv(codex_bin, [codex_bin, *config_args, *sys.argv[1:]])\n"
    )
    path.write_text(wrapper)
    path.chmod(0o700)


async def _run_turn(*, wrapper: Path, workspace: Path) -> None:
    settings = Settings.model_validate(
        {
            "a2a_static_auth_credentials": [
                {
                    "id": "live-smoke",
                    "scheme": "bearer",
                    "token": "local-live-smoke-token",
                    "principal": "live-smoke",
                }
            ],
            "a2a_database_url": None,
            "codex_cli_bin": str(wrapper),
            "codex_workspace_root": str(workspace),
            "codex_timeout": 30.0,
        }
    )
    client = CodexClient(settings)
    try:
        await asyncio.wait_for(client.startup_preflight(), timeout=45.0)
        session_id = await asyncio.wait_for(client.create_session(), timeout=30.0)
        message = await asyncio.wait_for(
            client.send_message(session_id, _PROMPT),
            timeout=45.0,
        )
    finally:
        await client.close()
    if message.text.strip() != _RESPONSE_TEXT:
        raise AssertionError(f"unexpected Codex turn response: {message.text!r}")


def main() -> None:
    codex_bin = shutil.which("codex")
    if codex_bin is None:
        raise SystemExit("codex not found in PATH")

    server = _SmokeResponsesServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="codex-a2a-live-smoke-") as temp_dir:
            temp_path = Path(temp_dir)
            workspace = temp_path / "workspace"
            workspace.mkdir()
            wrapper = temp_path / "codex-smoke-wrapper"
            _write_codex_wrapper(wrapper, codex_bin=codex_bin, provider_url=server.base_url)
            asyncio.run(_run_turn(wrapper=wrapper, workspace=workspace))
        if len(server.requests) != 1:
            raise AssertionError(f"expected one Responses API request, got {len(server.requests)}")
        if _PROMPT not in json.dumps(server.requests[0]):
            raise AssertionError("Codex turn did not forward the smoke prompt to the provider")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
