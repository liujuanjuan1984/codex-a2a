"""Inject configured authentication into TCK HTTP transport clients."""

from __future__ import annotations

import base64
import os
from typing import Any


def _authorization_header() -> str:
    auth_type = os.environ.get("A2A_AUTH_TYPE", "bearer").strip().lower()
    if auth_type == "bearer":
        token = os.environ.get("A2A_AUTH_TOKEN", "").strip()
        if not token:
            raise RuntimeError("A2A_AUTH_TOKEN is required for bearer TCK authentication")
        return f"Bearer {token}"
    if auth_type == "basic":
        username = os.environ.get("A2A_AUTH_USERNAME", "")
        password = os.environ.get("A2A_AUTH_PASSWORD", "")
        if not username or not password:
            raise RuntimeError(
                "A2A_AUTH_USERNAME and A2A_AUTH_PASSWORD are required for basic TCK authentication"
            )
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {encoded}"
    raise RuntimeError(f"Unsupported A2A_AUTH_TYPE for TCK authentication: {auth_type}")


def _patch_client(client_class: type[Any], authorization: str) -> None:
    original_init = client_class.__init__
    if getattr(original_init, "_codex_a2a_auth_patched", False):
        return

    def authenticated_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self._client.headers["Authorization"] = authorization

    authenticated_init._codex_a2a_auth_patched = True  # type: ignore[attr-defined]
    client_class.__init__ = authenticated_init


def pytest_configure() -> None:
    from tck.transport.http_json_client import HttpJsonClient
    from tck.transport.jsonrpc_client import JsonRpcClient

    authorization = _authorization_header()
    _patch_client(JsonRpcClient, authorization)
    _patch_client(HttpJsonClient, authorization)
