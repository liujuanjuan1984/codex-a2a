from __future__ import annotations

import httpx
from a2a.client import A2AClientError as SDKA2AClientError
from a2a.client.errors import A2AClientTimeoutError, AgentCardResolutionError


class A2AClientError(RuntimeError):
    """Base error for the codex-a2a A2A client facade."""

    error_code = "client_error"
    code: int | None = None
    data: object | None = None
    status_code: int | None = None


class A2AClientConfigError(A2AClientError):
    """Error in client configuration."""


class A2AClientLifecycleError(A2AClientError):
    """Lifecycle errors for the facade."""


class A2AClientRequestError(A2AClientError):
    """Base class for request/transport-level mapping errors."""


class A2AClientProtocolError(A2AClientError):
    """Base class for protocol-level mapping errors."""


class A2AAgentUnavailableError(A2AClientRequestError):
    """Remote peer is temporarily unavailable."""

    error_code = "agent_unavailable"


class A2AClientResetRequiredError(A2AAgentUnavailableError):
    """Cached client state should be reset and rebuilt."""

    error_code = "reset_required"


class A2AUnsupportedBindingError(A2AClientConfigError):
    """Local and remote transports have no overlap."""

    error_code = "unsupported_binding"


class A2AUnsupportedOperationError(A2AClientRequestError):
    """Peer does not support the requested operation."""

    error_code = "unsupported_operation"


class A2APeerProtocolError(A2AClientProtocolError):
    """Peer protocol or data contract mismatch."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "peer_protocol_error",
        rpc_code: int | None = None,
        status_code: int | None = None,
        data: object | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.code = rpc_code
        self.status_code = status_code
        self.data = data


def map_a2a_sdk_error(
    exc: Exception,
    *,
    operation: str | None = None,
) -> A2AClientError:
    """Convert SDK exceptions into local facade exceptions."""
    if isinstance(exc, AgentCardResolutionError):
        status_code = getattr(exc, "status_code", None)
        if status_code in {404, 405, 409, 501}:
            message = (
                f"{operation} is not supported by peer"
                if operation
                else f"Request failed with status={status_code}"
            )
            unsupported_error = A2AUnsupportedOperationError(message)
            unsupported_error.code = status_code
            unsupported_error.status_code = status_code
            return unsupported_error
        if status_code in {502, 503, 504}:
            message = f"{operation} failed with upstream instability" if operation else str(exc)
            reset_error = A2AClientResetRequiredError(message)
            reset_error.status_code = status_code
            return reset_error
        availability_error = A2AAgentUnavailableError(str(exc))
        availability_error.status_code = status_code
        return availability_error

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {404, 405, 409, 501}:
            unsupported_error = A2AUnsupportedOperationError(
                f"{operation} is not supported by peer"
                if operation
                else f"Request failed with status={status_code}"
            )
            unsupported_error.code = status_code
            unsupported_error.status_code = status_code
            return unsupported_error
        if status_code in {502, 503, 504}:
            reset_error = A2AClientResetRequiredError(
                f"{operation} failed with upstream instability" if operation else str(exc)
            )
            reset_error.status_code = status_code
            return reset_error
        availability_error = A2AAgentUnavailableError(str(exc))
        availability_error.status_code = status_code
        return availability_error

    if isinstance(exc, httpx.HTTPError):
        return A2AAgentUnavailableError(str(exc))

    if isinstance(exc, A2AClientTimeoutError):
        return A2AAgentUnavailableError(str(exc))

    if isinstance(exc, SDKA2AClientError):
        return A2AClientProtocolError(str(exc))

    return A2AClientError(str(exc))


__all__ = [
    "A2AClientError",
    "A2AClientConfigError",
    "A2AClientLifecycleError",
    "A2AClientRequestError",
    "A2AClientProtocolError",
    "A2AAgentUnavailableError",
    "A2AClientResetRequiredError",
    "A2AUnsupportedBindingError",
    "A2AUnsupportedOperationError",
    "A2APeerProtocolError",
    "map_a2a_sdk_error",
]
