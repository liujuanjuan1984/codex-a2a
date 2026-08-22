import pytest
from a2a.types import Role

from codex_a2a.jsonrpc.discovery_payload_mapping import (
    map_apps_list,
    map_plugin_detail,
    map_plugin_marketplaces,
    map_skill_scopes,
)
from codex_a2a.jsonrpc.payload_mapping import (
    as_a2a_message,
    as_a2a_session_task,
    extract_raw_items,
)


def test_map_skill_scopes_filters_invalid_entries_and_normalizes_strings() -> None:
    raw_scope = {
        "cwd": " /workspace/repo ",
        "skills": [
            {
                "name": " demo-skill ",
                "path": " /workspace/repo/.codex/skills/demo/SKILL.md ",
                "description": " Demo skill ",
                "enabled": True,
                "scope": " repo ",
                "interface": {"displayName": "Demo Skill"},
            },
            {
                "name": "missing-path",
                "path": " ",
                "description": "skip me",
                "enabled": True,
                "scope": "repo",
            },
        ],
        "errors": [{"message": "warn"}],
    }

    items = map_skill_scopes(
        {"data": [raw_scope, {"cwd": "/broken", "skills": "bad", "errors": []}]}
    )

    assert items == [
        {
            "skills": [
                {
                    "name": "demo-skill",
                    "description": "Demo skill",
                    "enabled": True,
                    "scope": "repo",
                    "interface": {"displayName": "Demo Skill"},
                }
            ],
            "errors": [{"message": "warn"}],
        }
    ]
    assert "/workspace" not in str(items)
    assert "raw" not in str(items)


def test_map_apps_list_normalizes_cursor_and_app_identity() -> None:
    items, next_cursor = map_apps_list(
        {
            "data": [
                {
                    "id": " demo-app ",
                    "name": " Demo App ",
                    "description": "Example connector",
                    "isAccessible": 1,
                    "isEnabled": 0,
                    "branding": {"icon": {"url": "https://internal.local/icon.png"}},
                    "labels": ["demo"],
                },
                {"id": "", "name": "broken"},
            ],
            "nextCursor": "",
        }
    )

    assert next_cursor is None
    assert items == [
        {
            "id": "demo-app",
            "name": "Demo App",
            "description": "Example connector",
            "is_accessible": True,
            "is_enabled": False,
            "install_url": None,
            "mention_path": "app://demo-app",
        }
    ]
    assert "branding" not in str(items)
    assert "labels" not in str(items)
    assert "internal.local" not in str(items)
    assert "raw" not in str(items)


def test_map_plugin_marketplaces_filters_plugin_metadata_and_keeps_sync_state() -> None:
    raw_marketplace = {
        "name": " curated ",
        "path": " /workspace/plugins/marketplace.json ",
        "interface": {"category": "utility"},
        "plugins": [
            {
                "name": " sample ",
                "description": "Sample plugin",
                "enabled": True,
                "interface": {"displayName": "Sample"},
            },
            {
                "name": " ",
                "description": "skip me",
            },
        ],
    }

    result = map_plugin_marketplaces(
        {
            "marketplaces": [raw_marketplace, {"name": "broken", "path": "x", "plugins": "bad"}],
            "featuredPluginIds": ["sample@curated", 42],
            "marketplaceLoadErrors": [{"path": "bad.json"}, "skip"],
            "remoteSyncError": "network timeout",
        }
    )

    assert result == {
        "items": [
            {
                "marketplace_name": "curated",
                "interface": {"category": "utility"},
                "plugins": [
                    {
                        "name": "sample",
                        "description": "Sample plugin",
                        "enabled": True,
                        "interface": {"displayName": "Sample"},
                        "mention_path": "plugin://sample@curated",
                    }
                ],
            }
        ],
        "featured_plugin_ids": ["sample@curated"],
        "marketplace_load_errors": [{"path": "bad.json"}],
        "remote_sync_error": "network timeout",
    }
    assert "/workspace" not in str(result)
    assert "raw" not in str(result)


def test_discovery_payload_mapping_rejects_invalid_top_level_shapes() -> None:
    with pytest.raises(ValueError, match="app/list payload must be an object"):
        map_apps_list([])

    with pytest.raises(ValueError, match="plugin/list payload missing marketplaces array"):
        map_plugin_marketplaces({"marketplaces": None})


def test_map_plugin_detail_requires_core_fields_and_filters_collections() -> None:
    result = map_plugin_detail(
        {
            "plugin": {
                "name": " sample ",
                "marketplaceName": " curated ",
                "marketplacePath": " /workspace/plugins/marketplace.json ",
                "summary": ["First", 1],
                "skills": [{"name": "skill-1"}, "skip"],
                "apps": [{"name": "app-1"}, "skip"],
                "mcpServers": ["server-1", 2],
                "interface": {"category": "utility"},
            }
        }
    )

    assert result == {
        "name": "sample",
        "marketplace_name": "curated",
        "mention_path": "plugin://sample@curated",
        "summary": ["First"],
        "skills": [{"name": "skill-1"}],
        "apps": [{"name": "app-1"}],
        "mcp_servers": ["server-1"],
        "interface": {"category": "utility"},
    }
    assert "/workspace" not in str(result)
    assert "raw" not in str(result)

    with pytest.raises(ValueError, match="plugin/read payload missing plugin.marketplaceName"):
        map_plugin_detail({"plugin": {"name": "sample", "marketplacePath": "/workspace/x"}})


def test_payload_mapping_contract_helpers_require_core_identifiers() -> None:
    task = as_a2a_session_task({"id": " sess-1 ", "title": " Demo Session "})
    assert task is not None
    assert task.id == "sess-1"
    assert task.context_id == "sess-1"
    assert task.metadata == {"codex": {"raw": {"id": " sess-1 ", "title": " Demo Session "}}}

    task_without_title = as_a2a_session_task({"id": "sess-2", "title": "  "})
    assert task_without_title is not None
    assert task_without_title.metadata == {"codex": {"raw": {"id": "sess-2", "title": "  "}}}

    message = as_a2a_message(
        "sess-1",
        {
            "info": {"id": " msg-1 ", "role": " user "},
            "parts": [{"type": "text", "text": "hello"}],
        },
    )

    assert message is not None
    assert message.message_id == "msg-1"
    assert message.role == Role.ROLE_USER
    assert message.context_id == "sess-1"
    assert message.metadata == {
        "codex": {
            "raw": {
                "info": {"id": " msg-1 ", "role": " user "},
                "parts": [{"type": "text", "text": "hello"}],
            }
        }
    }
    assert extract_raw_items([{"id": "ok"}], kind="sessions") == [{"id": "ok"}]

    with pytest.raises(ValueError, match="Codex sessions payload must be an array; got dict"):
        extract_raw_items({"id": "bad"}, kind="sessions")
