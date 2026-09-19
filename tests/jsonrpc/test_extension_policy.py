from types import SimpleNamespace
from typing import cast

import pytest
from a2a.server.context import ServerCallContext

from codex_a2a.jsonrpc.extension_policy import MethodExtensionCapabilityPolicy

_METHOD = "codex.example.call"
_EXTENSION_URI = "urn:codex-a2a:extension:example:v1"


class _MethodLookup:
    def extension_uri_for_method(self, method: str) -> str | None:
        return _EXTENSION_URI if method == _METHOD else None


@pytest.mark.asyncio
async def test_extension_capability_policy_awaits_async_authorizer() -> None:
    observed: list[tuple[str, str]] = []

    async def deny(method: str, extension_uri: str, _context: ServerCallContext) -> bool:
        observed.append((method, extension_uri))
        return False

    policy = MethodExtensionCapabilityPolicy(_MethodLookup(), authorizer=deny)
    context = cast(
        ServerCallContext,
        SimpleNamespace(requested_extensions=(_EXTENSION_URI,)),
    )

    decision = await policy.evaluate(_METHOD, context)

    assert observed == [(_METHOD, _EXTENSION_URI)]
    assert decision.activated is False
    assert decision.denial_reason == "activation_forbidden"
    assert decision.activated_extensions == ()
