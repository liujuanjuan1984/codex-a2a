from __future__ import annotations

from a2a.client import (
    A2AClientError as SDKA2AClientError,
    A2AClientHTTPError,
    A2AClientJSONError,
    A2AClientJSONRPCError,
    A2AClientTimeoutError,
)


class A2AClientError(RuntimeError):
    """Base error for the codex-a2a A2A client facade."""


class A2AClientConfigError(A2AClientError):
    """Error in client configuration."""


class A2AClientLifecycleError(A2AClientError):
    """Lifecycle errors for the facade."""


class A2AClientRequestError(A2AClientError):
    """Errors related to transport/http protocol operations."""

    status_code: int | None = None

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class A2AClientProtocolError(A2AClientError):
    """Errors returned by A2A protocol parsing/contract handling."""


def map_a2a_sdk_error(exc: Exception) -> A2AClientError:
    """Convert legacy SDK exceptions into local facade exceptions."""
    if isinstance(exc, A2AClientHTTPError):
        return A2AClientRequestError(
            str(exc),
            status_code=getattr(exc, "status_code", None),
        )
    if isinstance(exc, A2AClientTimeoutError):
        return A2AClientRequestError(str(exc))
    if isinstance(exc, (A2AClientJSONError, A2AClientJSONRPCError)):
        return A2AClientProtocolError(str(exc))
    if isinstance(exc, SDKA2AClientError):
        return A2AClientRequestError(str(exc))
    return A2AClientError(str(exc))
