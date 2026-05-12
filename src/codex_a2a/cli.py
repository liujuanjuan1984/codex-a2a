from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from uuid import uuid4

from a2a.types import Message, Role, SendMessageConfiguration, SendMessageRequest

from . import __version__
from .a2a_proto import new_text_part
from .client import A2AClient, A2AClientConfig
from .client.request_context import build_default_headers

CLI_REPOSITORY_URL = "https://github.com/liujuanjuan1984/codex-a2a"
CLI_BRAND_BANNER = "codex-a2a"
ROOT_DESCRIPTION = (
    "Codex A2A runtime for explicit service startup and peer calls. "
    "A2A Protocol 1.0 only.\n"
    "  codex-a2a <command> [arguments] [options]"
)
CODEX_SETUP_HELP = (
    "Codex runtime quick start:\n"
    "  codex --version\n"
    "  codex app-server --help\n"
    "\n"
    "Codex note:\n"
    "  Install and verify the local codex CLI before starting codex-a2a.\n"
    "  Configure Codex with a working provider, model, and required credentials."
)
SERVE_ENVIRONMENT_HELP = (
    "Serve required environment:\n"
    "  A2A_STATIC_AUTH_CREDENTIALS\n"
    "    JSON array with at least one enabled bearer/basic credential.\n"
    "\n"
    "Serve common environment:\n"
    "  A2A_HOST\n"
    "    Bind host. Default: 127.0.0.1\n"
    "  A2A_PORT\n"
    "    Bind port. Default: 8000\n"
    "  A2A_PUBLIC_URL\n"
    "    Public base URL advertised in the agent card. Default: http://127.0.0.1:8000\n"
    "  A2A_DATABASE_URL\n"
    "    Runtime state database. Defaults under ${CODEX_WORKSPACE_ROOT}/.codex-a2a/ when set.\n"
    "  CODEX_WORKSPACE_ROOT\n"
    "    Workspace root exposed to Codex tool execution.\n"
    "  CODEX_CLI_BIN\n"
    "    Codex CLI binary path. Default: codex\n"
    "  CODEX_MODEL\n"
    "    Default Codex model override.\n"
    "  CODEX_APPROVAL_POLICY\n"
    "    Default approval policy forwarded to codex app-server.\n"
    "  CODEX_SANDBOX_MODE\n"
    "    Default sandbox mode forwarded to codex app-server.\n"
    "\n"
    "Serve minimal example:\n"
    "  DEMO_BEARER_TOKEN=\"$(python -c 'import secrets; print(secrets.token_hex(24))')\"\n"
    '  A2A_STATIC_AUTH_CREDENTIALS=\'[{"id":"local-bearer","scheme":"bearer",'
    '"token":"\'"${DEMO_BEARER_TOKEN}"\'","principal":"automation"}]\' \\\n'
    "  CODEX_WORKSPACE_ROOT=/abs/path/to/workspace \\\n"
    "  codex-a2a serve\n"
    "\n"
    "Serve durable SQLite example:\n"
    "  DEMO_BEARER_TOKEN=\"$(python -c 'import secrets; print(secrets.token_hex(24))')\"\n"
    '  A2A_STATIC_AUTH_CREDENTIALS=\'[{"id":"local-bearer","scheme":"bearer",'
    '"token":"\'"${DEMO_BEARER_TOKEN}"\'","principal":"automation"}]\' \\\n'
    "  A2A_DATABASE_URL=sqlite+aiosqlite:////abs/path/to/workspace/.codex-a2a/codex-a2a.db \\\n"
    "  CODEX_WORKSPACE_ROOT=/abs/path/to/workspace \\\n"
    "  codex-a2a serve"
)
CALL_HELP = (
    "Call examples:\n"
    "  A2A_CLIENT_BEARER_TOKEN=peer-token \\\n"
    '  codex-a2a call http://other-agent:8000/.well-known/agent-card.json "How are you?"\n'
    "\n"
    '  A2A_CLIENT_BASIC_AUTH="user:pass" \\\n'
    '  codex-a2a call http://other-agent:8000/.well-known/agent-card.json "How are you?"\n'
    "\n"
    "Call note:\n"
    "  Outbound peer credentials are read from environment variables only.\n"
    "  Service base URLs also work, but card URLs are the preferred example form."
)
ROOT_HELP_EPILOG = f"{CODEX_SETUP_HELP}\n\n{SERVE_ENVIRONMENT_HELP}\n\n{CALL_HELP}"


class CliHelpFormatter(
    argparse.RawDescriptionHelpFormatter,
    argparse.ArgumentDefaultsHelpFormatter,
):
    """Preserve banner formatting while keeping argparse defaults."""


class TopLevelArgumentParser(argparse.ArgumentParser):
    """Trim generated top-level usage noise from root help output."""

    def format_help(self) -> str:
        help_text = super().format_help()
        lines = help_text.splitlines(keepends=True)
        if lines and lines[0].startswith("usage:"):
            help_text = "".join(lines[1:]).lstrip("\n")
        return help_text.replace("\ncommands:\n  command\n", "\ncommands:\n", 1)


async def run_call(
    agent_url: str,
    text: str,
    bearer_token: str | None = None,
    basic_auth: str | None = None,
) -> int:
    metadata: dict[str, object] = {}
    authorization_headers = build_default_headers(bearer_token, basic_auth)
    authorization = authorization_headers.get("Authorization")
    if authorization:
        metadata["authorization"] = authorization

    client = A2AClient(
        A2AClientConfig(
            agent_url=agent_url,
            default_headers=authorization_headers,
            request_timeout_seconds=None,
        )
    )
    try:
        first_chunk = True
        async for response in client.send_message(
            text,
            metadata=metadata or None,
            accepted_output_modes=["text/plain"],
        ):
            text_output = A2AClient.extract_text(response)
            if text_output:
                print(text_output, end="", flush=True)
                first_chunk = False
        if first_chunk:
            # Keep CLI behavior stable even when upstream emits no text payload.
            response = await client.send(
                SendMessageRequest(
                    message=Message(
                        message_id=f"msg-{uuid4().hex[:12]}",
                        role=Role.ROLE_USER,
                        parts=[new_text_part(text)],
                    ),
                    metadata=metadata or None,
                    configuration=SendMessageConfiguration(
                        accepted_output_modes=["text/plain"],
                    ),
                )
            )
            text_output = A2AClient.extract_text(response)
            if text_output:
                print(text_output, end="", flush=True)
        print()
    except Exception as exc:
        print(f"\n[Error] {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = TopLevelArgumentParser(
        prog="codex-a2a",
        description=(
            CLI_BRAND_BANNER
            + "\n\n"
            + f"repo: {CLI_REPOSITORY_URL}\n"
            + "uv tool install --upgrade codex-a2a\n"
            + ROOT_DESCRIPTION
        ),
        formatter_class=CliHelpFormatter,
        epilog=ROOT_HELP_EPILOG,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="command",
        parser_class=argparse.ArgumentParser,
    )
    subparsers.add_parser(
        "serve",
        help="Run the A2A service.",
    )
    call_parser = subparsers.add_parser(
        "call",
        help="Call an A2A agent.",
    )
    call_parser.add_argument("agent_url", help="Agent Card URL or A2A endpoint URL.")
    call_parser.add_argument("text", help="Message text.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args:
        parser.print_help()
        return 0

    namespace = parser.parse_args(args)
    if namespace.command == "serve":
        from .server.application import main as serve_main

        serve_main()
        return 0

    if namespace.command is None:
        parser.print_help()
        return 0

    if namespace.command == "call":
        return asyncio.run(
            run_call(
                namespace.agent_url,
                namespace.text,
                bearer_token=os.environ.get("A2A_CLIENT_BEARER_TOKEN"),
                basic_auth=os.environ.get("A2A_CLIENT_BASIC_AUTH"),
            )
        )

    parser.error(f"Unknown command: {namespace.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
