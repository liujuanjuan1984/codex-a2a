import pytest

from codex_a2a.contracts.extensions import (
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_MAX_LIMIT,
)
from codex_a2a.jsonrpc.params import (
    JsonRpcParamsValidationError,
    parse_discovery_apps_list_params,
    parse_discovery_plugin_read_params,
    parse_discovery_plugins_list_params,
    parse_discovery_skills_list_params,
    parse_discovery_watch_params,
    parse_elicitation_reply_params,
    parse_get_session_messages_params,
    parse_list_sessions_params,
    parse_permission_reply_params,
    parse_permissions_reply_params,
    parse_prompt_async_params,
)


def test_parse_prompt_async_params_preserves_aliases() -> None:
    payload = parse_prompt_async_params(
        {
            "session_id": "s-1",
            "request": {
                "parts": [{"type": "text", "text": "hello"}],
                "messageID": "msg-1",
            },
            "metadata": {"codex": {"directory": "/workspace"}},
        }
    )

    assert payload.session_id == "s-1"
    assert payload.request.model_dump(by_alias=True, exclude_none=True) == {
        "parts": [{"type": "text", "text": "hello"}],
        "messageID": "msg-1",
    }
    assert payload.metadata is not None
    assert payload.metadata.codex is not None
    assert payload.metadata.codex.directory == "/workspace"


def test_parse_prompt_async_params_accepts_rich_input_parts() -> None:
    payload = parse_prompt_async_params(
        {
            "session_id": "s-1",
            "request": {
                "parts": [
                    {"type": "text", "text": "Summarize the screenshot."},
                    {
                        "type": "image",
                        "url": "https://example.com/screenshot.png",
                    },
                    {
                        "type": "mention",
                        "name": "Demo App",
                        "path": "app://demo-app",
                    },
                    {
                        "type": "skill",
                        "name": "skill-creator",
                        "path": "/tmp/skill-creator/SKILL.md",
                    },
                ]
            },
        }
    )

    assert payload.request.model_dump(by_alias=True, exclude_none=True)["parts"] == [
        {"type": "text", "text": "Summarize the screenshot."},
        {"type": "image", "url": "https://example.com/screenshot.png"},
        {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
        {
            "type": "skill",
            "name": "skill-creator",
            "path": "/tmp/skill-creator/SKILL.md",
        },
    ]


@pytest.mark.parametrize(
    ("payload", "message", "data"),
    [
        (
            {
                "session_id": "s-1",
                "request": {
                    "parts": [{"type": "text", "text": "hello"}],
                    "extra": True,
                },
            },
            "Unsupported fields: request.extra",
            {
                "type": "INVALID_FIELD",
                "field": "request",
                "fields": ["request.extra"],
            },
        ),
        (
            {
                "session_id": "s-1",
                "request": {"parts": [{"type": "text", "text": "hello"}]},
                "metadata": {"extra": True},
            },
            "Unsupported metadata fields: extra",
            {
                "type": "INVALID_FIELD",
                "fields": ["metadata.extra"],
            },
        ),
    ],
)
def test_parse_prompt_async_params_rejects_unknown_fields(
    payload: dict,
    message: str,
    data: dict,
) -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_prompt_async_params(payload)

    assert str(exc_info.value) == message
    assert exc_info.value.data == data


def test_parse_permission_reply_params_rejects_missing_reply() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_permission_reply_params({"request_id": "perm-1"})

    assert str(exc_info.value) == "reply must be a string"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "reply"}
    assert "fields" not in exc_info.value.data


def test_parse_permissions_reply_params_accepts_scope_and_permissions_object() -> None:
    payload = parse_permissions_reply_params(
        {
            "request_id": "perm-2",
            "permissions": {"fileSystem": {"write": ["/workspace"]}},
            "scope": "session",
        }
    )

    assert payload.request_id == "perm-2"
    assert payload.permissions == {"fileSystem": {"write": ["/workspace"]}}
    assert payload.scope == "session"


def test_parse_permissions_reply_params_rejects_non_object_permissions() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_permissions_reply_params({"request_id": "perm-2", "permissions": []})

    assert str(exc_info.value) == "permissions must be an object"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "permissions"}


def test_parse_elicitation_reply_params_rejects_non_null_content_for_decline() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_elicitation_reply_params(
            {"request_id": "eli-1", "action": "decline", "content": {"ignored": True}}
        )

    assert str(exc_info.value) == "content must be null when action is decline or cancel"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "content"}


def test_parse_list_sessions_params_rejects_non_integer_limit() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_list_sessions_params({"limit": "abc"})

    assert str(exc_info.value) == "limit must be an integer"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "limit"}
    assert "fields" not in exc_info.value.data


def test_parse_list_sessions_params_applies_default_limit() -> None:
    query = parse_list_sessions_params({})

    assert query == {"limit": SESSION_QUERY_DEFAULT_LIMIT}


def test_parse_list_sessions_params_rejects_limit_above_max() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_list_sessions_params({"limit": SESSION_QUERY_MAX_LIMIT + 1})

    assert str(exc_info.value) == f"limit must be <= {SESSION_QUERY_MAX_LIMIT}"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "limit"}


def test_parse_get_session_messages_params_returns_session_and_query() -> None:
    session_id, query = parse_get_session_messages_params(
        {
            "session_id": "s-1",
            "limit": "3",
            "query": {"cursor": None, "tag": "ops"},
        }
    )

    assert session_id == "s-1"
    assert query == {"tag": "ops", "limit": 3}


def test_parse_get_session_messages_params_applies_default_limit() -> None:
    session_id, query = parse_get_session_messages_params({"session_id": "s-1"})

    assert session_id == "s-1"
    assert query == {"limit": SESSION_QUERY_DEFAULT_LIMIT}


def test_parse_prompt_async_params_only_uses_fields_for_unsupported_fields() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as unsupported_exc:
        parse_prompt_async_params(
            {
                "session_id": "s-1",
                "request": {
                    "parts": [{"type": "text", "text": "hello"}],
                    "extra": True,
                },
            }
        )

    assert unsupported_exc.value.data["field"] == "request"
    assert unsupported_exc.value.data["fields"] == ["request.extra"]

    with pytest.raises(JsonRpcParamsValidationError) as invalid_type_exc:
        parse_prompt_async_params(
            {
                "session_id": "s-1",
                "request": {"parts": [{"type": "text", "text": 1}]},
            }
        )

    assert invalid_type_exc.value.data == {
        "type": "INVALID_FIELD",
        "field": "request.parts[0].text",
    }
    assert "fields" not in invalid_type_exc.value.data


def test_parse_prompt_async_params_rejects_unknown_part_type() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_prompt_async_params(
            {
                "session_id": "s-1",
                "request": {"parts": [{"type": "file", "path": "/tmp/x"}]},
            }
        )

    assert str(exc_info.value) == "request.parts[].type must be one of: text, image, mention, skill"
    assert exc_info.value.data == {
        "type": "INVALID_FIELD",
        "field": "request.parts[0].type",
    }


def test_parse_discovery_param_aliases_preserve_upstream_shapes() -> None:
    skills = parse_discovery_skills_list_params(
        {
            "cwds": ["/workspace/project"],
            "force_reload": True,
            "per_cwd_extra_user_roots": [
                {
                    "cwd": "/workspace/project",
                    "extra_user_roots": ["/workspace/shared-skills"],
                }
            ],
        }
    )
    apps = parse_discovery_apps_list_params(
        {
            "limit": 20,
            "thread_id": "thr-1",
            "force_refetch": False,
        }
    )
    plugins = parse_discovery_plugins_list_params(
        {
            "cwds": ["/workspace/project"],
            "force_remote_sync": True,
        }
    )
    plugin = parse_discovery_plugin_read_params(
        {
            "marketplace_path": "/workspace/project/.codex/plugins/marketplace.json",
            "plugin_name": "sample",
        }
    )

    assert skills == {
        "cwds": ["/workspace/project"],
        "forceReload": True,
        "perCwdExtraUserRoots": [
            {
                "cwd": "/workspace/project",
                "extraUserRoots": ["/workspace/shared-skills"],
            }
        ],
    }
    assert apps == {"limit": 20, "threadId": "thr-1", "forceRefetch": False}
    assert plugins == {
        "cwds": ["/workspace/project"],
        "forceRemoteSync": True,
    }
    assert plugin == {
        "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
        "pluginName": "sample",
    }
    assert parse_discovery_watch_params({"request": {"events": ["skills.changed"]}}) == {
        "request": {"events": ["skills.changed"]}
    }


@pytest.mark.parametrize(
    ("parser", "payload", "field"),
    [
        (parse_discovery_skills_list_params, {"cwds": [""]}, "cwds"),
        (parse_discovery_apps_list_params, {"limit": 0}, "limit"),
        (
            parse_discovery_plugin_read_params,
            {"marketplacePath": "", "pluginName": "sample"},
            "marketplace_path",
        ),
    ],
)
def test_parse_discovery_params_reject_invalid_fields(parser, payload, field: str) -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parser(payload)

    assert exc_info.value.data["field"] == field
