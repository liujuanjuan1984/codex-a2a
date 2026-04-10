from __future__ import annotations

from typing import Any


def normalize_app_item(app: Any) -> dict[str, Any] | None:
    if not isinstance(app, dict):
        return None
    app_id = app.get("id")
    name = app.get("name")
    if not isinstance(app_id, str) or not app_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    normalized_app_id = app_id.strip()
    return {
        "id": normalized_app_id,
        "name": name.strip(),
        "description": app.get("description"),
        "is_accessible": bool(app.get("isAccessible", False)),
        "is_enabled": bool(app.get("isEnabled", False)),
        "install_url": app.get("installUrl"),
        "mention_path": f"app://{normalized_app_id}",
        "branding": app.get("branding"),
        "labels": app.get("labels"),
        "codex": {"raw": app},
    }


def normalize_app_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for app in value if (item := normalize_app_item(app)) is not None]
