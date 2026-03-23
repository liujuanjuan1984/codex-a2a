"""Minimal A2A client facade package."""

from .client import A2AClient
from .config import A2AClientConfig
from .errors import (
    A2AAgentUnavailableError,
    A2AClientError,
    A2AClientLifecycleError,
    A2AClientProtocolError,
    A2AClientRequestError,
    A2AClientResetRequiredError,
    A2APeerProtocolError,
    A2AUnsupportedBindingError,
    A2AUnsupportedOperationError,
)
from .manager import A2AClientManager
from .types import (
    A2ACancelTaskRequest,
    A2AGetTaskRequest,
    A2ASendRequest,
)

__all__ = [
    "A2AClient",
    "A2AClientManager",
    "A2AClientConfig",
    "A2AClientError",
    "A2AClientLifecycleError",
    "A2AClientProtocolError",
    "A2AClientRequestError",
    "A2AAgentUnavailableError",
    "A2AClientResetRequiredError",
    "A2AUnsupportedBindingError",
    "A2AUnsupportedOperationError",
    "A2APeerProtocolError",
    "A2ACancelTaskRequest",
    "A2AGetTaskRequest",
    "A2ASendRequest",
]
