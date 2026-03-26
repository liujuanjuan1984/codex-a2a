from __future__ import annotations

import tempfile
import uuid
from typing import Any

from codex_a2a.config import Settings


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "a2a_bearer_token": "test-token",
        "a2a_database_url": (
            f"sqlite+aiosqlite:///{tempfile.gettempdir()}/codex-a2a-test-{uuid.uuid4().hex}.db"
        ),
    }
    base.update(overrides)
    return Settings(**base)
