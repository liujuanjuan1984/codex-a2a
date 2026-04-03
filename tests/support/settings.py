from __future__ import annotations

from typing import Any

from codex_a2a.config import Settings


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "a2a_bearer_token": "test-token",
        "a2a_database_url": None,
        "a2a_enable_session_shell": True,
        "a2a_enable_turn_control": True,
        "a2a_enable_review_control": True,
        "a2a_enable_exec_control": True,
    }
    base.update(overrides)
    return Settings(**base)
