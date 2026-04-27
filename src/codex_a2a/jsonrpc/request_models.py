from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class JSONRPCRequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str
    method: str
    id: str | int | None = None
    params: dict[str, Any] | None = None
