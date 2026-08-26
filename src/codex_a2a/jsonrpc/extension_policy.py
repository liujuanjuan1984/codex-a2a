from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from a2a.server.context import ServerCallContext


class ExtensionMethodLookup(Protocol):
    def extension_uri_for_method(self, method: str) -> str | None: ...


class ExtensionActivationAuthorizer(Protocol):
    def __call__(
        self,
        method: str,
        extension_uri: str,
        context: ServerCallContext,
    ) -> bool: ...


@dataclass(frozen=True)
class ExtensionActivationDecision:
    method: str
    extension_uri: str
    requested_extensions: tuple[str, ...]
    activated_extensions: tuple[str, ...]
    denial_reason: Literal["negotiation_required", "activation_forbidden"] | None = None

    @property
    def activated(self) -> bool:
        return self.denial_reason is None


class MethodExtensionCapabilityPolicy:
    """Evaluate request-level activation before an extension method is dispatched."""

    def __init__(
        self,
        method_lookup: ExtensionMethodLookup,
        *,
        authorizer: ExtensionActivationAuthorizer | None = None,
    ) -> None:
        self._method_lookup = method_lookup
        self._authorizer = authorizer

    def evaluate(
        self,
        method: str,
        context: ServerCallContext,
    ) -> ExtensionActivationDecision:
        extension_uri = self._method_lookup.extension_uri_for_method(method)
        if extension_uri is None:
            raise ValueError(f"Method is not registered as an extension method: {method}")

        requested_extensions = tuple(sorted(set(context.requested_extensions)))
        if extension_uri not in requested_extensions:
            return ExtensionActivationDecision(
                method=method,
                extension_uri=extension_uri,
                requested_extensions=requested_extensions,
                activated_extensions=(),
                denial_reason="negotiation_required",
            )
        if self._authorizer is not None and not self._authorizer(
            method,
            extension_uri,
            context,
        ):
            return ExtensionActivationDecision(
                method=method,
                extension_uri=extension_uri,
                requested_extensions=requested_extensions,
                activated_extensions=(),
                denial_reason="activation_forbidden",
            )
        return ExtensionActivationDecision(
            method=method,
            extension_uri=extension_uri,
            requested_extensions=requested_extensions,
            activated_extensions=(extension_uri,),
        )
