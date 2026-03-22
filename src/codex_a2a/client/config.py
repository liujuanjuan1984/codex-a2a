from __future__ import annotations

from pydantic import BaseModel, Field


class A2AClientConfig(BaseModel):
    """Configuration for the minimal A2A client facade."""

    agent_url: str
    agent_card_path: str = Field(default="/.well-known/agent-card.json")
    supported_transports: list[str] = Field(default_factory=lambda: ["jsonrpc"])
    use_client_preference: bool = False
    request_timeout_seconds: float | None = None
    close_http_client: bool = True
    default_headers: dict[str, str] = Field(default_factory=dict)
    accepted_output_modes: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)

    def resolved_agent_url(self) -> str:
        return self.agent_url.rstrip("/")
