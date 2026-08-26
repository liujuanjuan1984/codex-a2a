from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class JSONRPCRequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str
    method: str
    id: str | int | None = None
    # Keep the preliminary request model permissive enough to identify extension
    # methods before method-specific params validation runs in the dispatcher.
    params: Any = None
