from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from .config import A2AClientConfig
from .errors import A2AClientConfigError


@dataclass(frozen=True)
class AgentCardEndpoint:
    base_url: str
    agent_card_path: str


def resolve_agent_card_endpoint(config: A2AClientConfig) -> AgentCardEndpoint:
    resolved_url = config.agent_url.rstrip("/")
    parsed_url = urlsplit(resolved_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        raise A2AClientConfigError(f"agent_url must be absolute URL: {resolved_url}")

    normalized_no_leading = (parsed_url.path or "").rstrip("/").lstrip("/")
    candidate_paths = (
        AGENT_CARD_WELL_KNOWN_PATH,
        PREV_AGENT_CARD_WELL_KNOWN_PATH,
        EXTENDED_AGENT_CARD_PATH,
    )

    base_path = normalized_no_leading
    agent_card_path = config.agent_card_path
    for candidate_path in candidate_paths:
        card_suffix = candidate_path.lstrip("/")
        if normalized_no_leading.endswith(card_suffix):
            base_path = normalized_no_leading[: -len(card_suffix)].rstrip("/")
            agent_card_path = candidate_path
            break

    base_url = urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            f"/{base_path}" if base_path else "",
            "",
            "",
        )
    ).rstrip("/")
    return AgentCardEndpoint(base_url=base_url, agent_card_path=agent_card_path)


def build_agent_card_request_kwargs(config: A2AClientConfig) -> dict[str, Any]:
    http_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(config.card_fetch_timeout_seconds),
    }
    if config.default_headers:
        http_kwargs["headers"] = {
            key: str(value) for key, value in config.default_headers.items() if value is not None
        }
    return http_kwargs
