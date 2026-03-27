from __future__ import annotations

from typing import Any


def _normalized_interface(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return dict(value)


def map_skill_scopes(raw_result: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_result, dict):
        raise ValueError("skills/list payload must be an object")
    data = raw_result.get("data")
    if not isinstance(data, list):
        raise ValueError("skills/list payload missing data array")
    items: list[dict[str, Any]] = []
    for scope_entry in data:
        if not isinstance(scope_entry, dict):
            continue
        cwd = scope_entry.get("cwd")
        skills = scope_entry.get("skills")
        errors = scope_entry.get("errors")
        if not isinstance(cwd, str) or not isinstance(skills, list) or not isinstance(errors, list):
            continue
        normalized_skills: list[dict[str, Any]] = []
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            name = skill.get("name")
            path = skill.get("path")
            description = skill.get("description")
            enabled = skill.get("enabled")
            scope = skill.get("scope")
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(path, str) or not path.strip():
                continue
            if not isinstance(description, str) or not description.strip():
                continue
            if not isinstance(scope, str) or not scope.strip():
                continue
            if not isinstance(enabled, bool):
                continue
            normalized_skills.append(
                {
                    "name": name.strip(),
                    "path": path.strip(),
                    "description": description.strip(),
                    "enabled": enabled,
                    "scope": scope.strip(),
                    "interface": _normalized_interface(skill.get("interface")),
                    "codex": {"raw": skill},
                }
            )
        items.append(
            {
                "cwd": cwd.strip(),
                "skills": normalized_skills,
                "errors": [error for error in errors if isinstance(error, dict)],
                "codex": {"raw": scope_entry},
            }
        )
    return items


def map_apps_list(raw_result: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(raw_result, dict):
        raise ValueError("app/list payload must be an object")
    data = raw_result.get("data")
    if not isinstance(data, list):
        raise ValueError("app/list payload missing data array")
    items: list[dict[str, Any]] = []
    for app in data:
        if not isinstance(app, dict):
            continue
        app_id = app.get("id")
        name = app.get("name")
        if not isinstance(app_id, str) or not app_id.strip():
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        items.append(
            {
                "id": app_id.strip(),
                "name": name.strip(),
                "description": app.get("description"),
                "is_accessible": bool(app.get("isAccessible", False)),
                "is_enabled": bool(app.get("isEnabled", False)),
                "install_url": app.get("installUrl"),
                "mention_path": f"app://{app_id.strip()}",
                "branding": app.get("branding"),
                "labels": app.get("labels"),
                "codex": {"raw": app},
            }
        )
    next_cursor = raw_result.get("nextCursor")
    return items, next_cursor if isinstance(next_cursor, str) and next_cursor else None


def map_plugin_marketplaces(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise ValueError("plugin/list payload must be an object")
    marketplaces = raw_result.get("marketplaces")
    if not isinstance(marketplaces, list):
        raise ValueError("plugin/list payload missing marketplaces array")
    items: list[dict[str, Any]] = []
    for marketplace in marketplaces:
        if not isinstance(marketplace, dict):
            continue
        marketplace_name = marketplace.get("name")
        marketplace_path = marketplace.get("path")
        plugins = marketplace.get("plugins")
        if not isinstance(marketplace_name, str) or not marketplace_name.strip():
            continue
        if not isinstance(marketplace_path, str) or not marketplace_path.strip():
            continue
        if not isinstance(plugins, list):
            continue
        normalized_plugins: list[dict[str, Any]] = []
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            name = plugin.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            normalized_plugins.append(
                {
                    "name": name.strip(),
                    "description": plugin.get("description"),
                    "enabled": plugin.get("enabled"),
                    "interface": _normalized_interface(plugin.get("interface")),
                    "mention_path": f"plugin://{name.strip()}@{marketplace_name.strip()}",
                    "codex": {"raw": plugin},
                }
            )
        items.append(
            {
                "marketplace_name": marketplace_name.strip(),
                "marketplace_path": marketplace_path.strip(),
                "interface": _normalized_interface(marketplace.get("interface")),
                "plugins": normalized_plugins,
                "codex": {"raw": marketplace},
            }
        )
    return {
        "items": items,
        "featured_plugin_ids": [
            value for value in raw_result.get("featuredPluginIds", []) if isinstance(value, str)
        ],
        "marketplace_load_errors": [
            value
            for value in raw_result.get("marketplaceLoadErrors", [])
            if isinstance(value, dict)
        ],
        "remote_sync_error": (
            raw_result.get("remoteSyncError")
            if isinstance(raw_result.get("remoteSyncError"), str)
            else None
        ),
    }


def map_plugin_detail(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise ValueError("plugin/read payload must be an object")
    plugin = raw_result.get("plugin")
    if not isinstance(plugin, dict):
        raise ValueError("plugin/read payload missing plugin object")
    name = plugin.get("name")
    marketplace_name = plugin.get("marketplaceName")
    marketplace_path = plugin.get("marketplacePath")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("plugin/read payload missing plugin.name")
    if not isinstance(marketplace_name, str) or not marketplace_name.strip():
        raise ValueError("plugin/read payload missing plugin.marketplaceName")
    if not isinstance(marketplace_path, str) or not marketplace_path.strip():
        raise ValueError("plugin/read payload missing plugin.marketplacePath")
    return {
        "name": name.strip(),
        "marketplace_name": marketplace_name.strip(),
        "marketplace_path": marketplace_path.strip(),
        "mention_path": f"plugin://{name.strip()}@{marketplace_name.strip()}",
        "summary": [value for value in plugin.get("summary", []) if isinstance(value, str)],
        "skills": [value for value in plugin.get("skills", []) if isinstance(value, dict)],
        "apps": [value for value in plugin.get("apps", []) if isinstance(value, dict)],
        "mcp_servers": [value for value in plugin.get("mcpServers", []) if isinstance(value, str)],
        "interface": _normalized_interface(plugin.get("interface")),
        "codex": {"raw": plugin},
    }
