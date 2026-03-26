from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from . import __version__
from .client import A2AClient, A2AClientConfig
from .client.request_context import build_default_headers
from .client.types import A2ASendRequest


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
                A2ASendRequest(
                    text=text,
                    metadata=metadata or None,
                    accepted_output_modes=["text/plain"],
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


def _serve_main() -> None:
    from .server.application import main as serve_main

    serve_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-a2a",
        description="Codex A2A CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "serve",
        help="Start the Codex A2A runtime.",
    )
    call_parser = subparsers.add_parser(
        "call",
        help="Call an A2A agent and print text responses.",
    )
    call_parser.add_argument("agent_url", help="A2A endpoint URL.")
    call_parser.add_argument("text", help="Message text.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not args:
        _serve_main()
        return 0

    namespace = parser.parse_args(args)
    if namespace.command == "serve" or namespace.command is None:
        _serve_main()
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
