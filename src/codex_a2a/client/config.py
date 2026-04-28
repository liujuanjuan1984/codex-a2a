from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator


class A2AClientConfig(BaseModel):
    """Configuration for the minimal A2A client facade."""

    agent_url: str
    agent_card_path: str = Field(default="/.well-known/agent-card.json")
    supported_transports: list[str] = Field(default_factory=lambda: ["JSONRPC"])
    card_fetch_timeout_seconds: float = 5.0
    use_client_preference: bool = False
    request_timeout_seconds: float | None = None
    close_http_client: bool = True
    default_headers: dict[str, str] = Field(default_factory=dict)
    auth_credentials: dict[str, str] = Field(default_factory=dict)
    accepted_output_modes: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)

    @field_validator("card_fetch_timeout_seconds")
    @classmethod
    def validate_card_fetch_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("card_fetch_timeout_seconds must be > 0")
        return value

    @field_validator("extensions", mode="before")
    @classmethod
    def normalize_extensions(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, Sequence):
            values = [str(item) for item in value]
        else:
            raise ValueError("extensions must be a string or sequence of strings")

        normalized: list[str] = []
        for item in values:
            extension = str(item).strip()
            if extension and extension not in normalized:
                normalized.append(extension)
        return normalized
