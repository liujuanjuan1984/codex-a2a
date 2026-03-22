"""Minimal A2A client facade package."""

from .client import A2AClient
from .config import A2AClientConfig
from .errors import (
    A2AClientError,
    A2AClientLifecycleError,
    A2AClientProtocolError,
    A2AClientRequestError,
)
from .types import (
    A2ACancelTaskRequest,
    A2AGetTaskRequest,
    A2ASendRequest,
)

__all__ = [
    "A2AClient",
    "A2AClientConfig",
    "A2AClientError",
    "A2AClientLifecycleError",
    "A2AClientProtocolError",
    "A2AClientRequestError",
    "A2ACancelTaskRequest",
    "A2AGetTaskRequest",
    "A2ASendRequest",
]
