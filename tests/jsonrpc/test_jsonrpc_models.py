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
    parse_interrupt_recovery_list_params,
    parse_list_sessions_params,
    parse_permission_reply_params,
    parse_permissions_reply_params,
    parse_review_start_params,
    parse_review_watch_params,
    parse_thread_archive_params,
    parse_thread_fork_params,
    parse_thread_metadata_update_params,
    parse_thread_watch_params,
    parse_thread_watch_release_params,
    parse_turn_steer_params,
)


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


def test_parse_interrupt_recovery_list_params_accepts_type_aliases() -> None:
    payload = parse_interrupt_recovery_list_params({"interruptType": "permissions"})

    assert payload.interrupt_type == "permissions"


def test_parse_interrupt_recovery_list_params_rejects_invalid_type() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parse_interrupt_recovery_list_params({"type": "unknown"})

    assert str(exc_info.value) == (
        "type must be one of: permission, question, permissions, elicitation"
    )
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "type"}


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


def test_parse_thread_lifecycle_params_preserve_aliases() -> None:
    fork = parse_thread_fork_params(
        {
            "threadId": "thr-1",
            "request": {"ephemeral": True},
            "metadata": {"codex": {"directory": "/workspace"}},
        }
    )
    metadata_update = parse_thread_metadata_update_params(
        {
            "thread_id": "thr-1",
            "request": {"gitInfo": {"branch": "feat/thread-lifecycle", "originUrl": "https://x"}},
        }
    )
    watch = parse_thread_watch_params(
        {
            "request": {
                "events": ["thread.started", "thread.status.changed", "thread.started"],
                "threadIds": ["thr-1", "thr-2", "thr-1"],
            }
        }
    )
    watch_release = parse_thread_watch_release_params({"taskId": "task-watch-1"})

    assert fork.thread_id == "thr-1"
    assert fork.request is not None
    assert fork.request.model_dump(by_alias=True, exclude_none=True) == {"ephemeral": True}
    assert fork.metadata is not None
    assert fork.metadata.codex is not None
    assert fork.metadata.codex.directory == "/workspace"
    assert metadata_update.request.model_dump(by_alias=True, exclude_none=True) == {
        "gitInfo": {
            "branch": "feat/thread-lifecycle",
            "originUrl": "https://x",
        }
    }
    assert watch.request is not None
    assert watch.request.model_dump(by_alias=True, exclude_none=True) == {
        "events": ["thread.started", "thread.status.changed"],
        "threadIds": ["thr-1", "thr-2"],
    }
    assert watch_release.task_id == "task-watch-1"


def test_parse_turn_and_review_control_params_preserve_aliases() -> None:
    steer = parse_turn_steer_params(
        {
            "threadId": "thr-1",
            "expectedTurnId": "turn-1",
            "request": {
                "parts": [
                    {"type": "text", "text": "Focus on the failing tests first."},
                    {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                ]
            },
        }
    )
    review = parse_review_start_params(
        {
            "thread_id": "thr-1",
            "delivery": "detached",
            "target": {
                "type": "commit",
                "sha": "commit-demo-123",
                "title": "Polish tui colors",
            },
        }
    )
    review_watch = parse_review_watch_params(
        {
            "threadId": "thr-1",
            "reviewThreadId": "thr-1-review",
            "turnId": "turn-review-1",
            "request": {"events": ["review.started", "review.completed", "review.started"]},
        }
    )

    assert steer.thread_id == "thr-1"
    assert steer.expected_turn_id == "turn-1"
    assert steer.request.model_dump(by_alias=True, exclude_none=True) == {
        "parts": [
            {"type": "text", "text": "Focus on the failing tests first."},
            {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
        ]
    }
    assert review.thread_id == "thr-1"
    assert review.delivery == "detached"
    assert review.target.model_dump(by_alias=True, exclude_none=True) == {
        "type": "commit",
        "sha": "commit-demo-123",
        "title": "Polish tui colors",
    }
    assert review_watch.thread_id == "thr-1"
    assert review_watch.review_thread_id == "thr-1-review"
    assert review_watch.turn_id == "turn-review-1"
    assert review_watch.request is not None
    assert review_watch.request.model_dump(by_alias=True, exclude_none=True) == {
        "events": ["review.started", "review.completed"]
    }


@pytest.mark.parametrize(
    ("parser", "payload", "message", "field"),
    [
        (
            parse_thread_archive_params,
            {"thread_id": "   "},
            "Missing required params.thread_id",
            "thread_id",
        ),
        (
            parse_thread_fork_params,
            {"thread_id": "thr-1", "request": {"ephemeral": "yes"}},
            "request.ephemeral must be a boolean",
            "request.ephemeral",
        ),
        (
            parse_thread_metadata_update_params,
            {"thread_id": "thr-1", "request": {"gitInfo": {}}},
            "request.git_info must include at least one field",
            "request.git_info",
        ),
        (
            parse_thread_watch_params,
            {"request": {"events": ["thread.deleted"]}},
            (
                "request.events entries must be one of: thread.started, "
                "thread.status.changed, thread.archived, thread.unarchived, thread.closed"
            ),
            "request.events",
        ),
        (
            parse_thread_watch_params,
            {"request": {"threadIds": ["thr-1", "  "]}},
            "request.thread_ids[] must be a non-empty string",
            "request.thread_ids",
        ),
        (
            parse_thread_watch_release_params,
            {"task_id": "   "},
            "Missing required params.task_id",
            "task_id",
        ),
    ],
)
def test_parse_thread_lifecycle_params_reject_invalid_fields(
    parser,
    payload: dict,
    message: str,
    field: str,
) -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parser(payload)

    assert str(exc_info.value) == message
    assert exc_info.value.data["type"] in {"MISSING_FIELD", "INVALID_FIELD"}
    assert exc_info.value.data["field"] == field


@pytest.mark.parametrize(
    ("parser", "payload", "message", "field"),
    [
        (
            parse_turn_steer_params,
            {
                "thread_id": "thr-1",
                "expected_turn_id": "turn-1",
                "request": {"parts": []},
            },
            "request.parts must be a non-empty array",
            "request.parts",
        ),
        (
            parse_turn_steer_params,
            {
                "thread_id": "thr-1",
                "expected_turn_id": "turn-1",
                "request": {"parts": [{"type": "file", "path": "/tmp/x"}]},
            },
            "request.parts[].type must be one of: text, image, mention, skill",
            "request.parts[0].type",
        ),
        (
            parse_review_start_params,
            {"thread_id": "thr-1", "delivery": "queued", "target": {"type": "commit", "sha": "a"}},
            "delivery must be one of: inline, detached",
            "delivery",
        ),
        (
            parse_review_start_params,
            {"thread_id": "thr-1", "target": {"type": "baseBranch"}},
            "target.branch must be a non-empty string",
            "target.branch",
        ),
        (
            parse_review_start_params,
            {"thread_id": "thr-1", "target": {"type": "custom", "instructions": "   "}},
            "target.instructions must be a non-empty string",
            "target.instructions",
        ),
        (
            parse_review_watch_params,
            {
                "thread_id": "thr-1",
                "review_thread_id": "thr-1-review",
                "turn_id": "turn-review-1",
                "request": {"events": ["review.delta"]},
            },
            (
                "request.events entries must be one of: review.started, "
                "review.status.changed, review.completed, review.failed"
            ),
            "request.events",
        ),
        (
            parse_review_watch_params,
            {
                "thread_id": "thr-1",
                "review_thread_id": "thr-1-review",
                "turn_id": "turn-review-1",
                "request": {"events": []},
            },
            "request.events must be a non-empty array",
            "request.events",
        ),
    ],
)
def test_parse_turn_and_review_control_params_reject_invalid_fields(
    parser,
    payload: dict,
    message: str,
    field: str,
) -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parser(payload)

    assert str(exc_info.value) == message
    assert exc_info.value.data["type"] == "INVALID_FIELD"
    assert exc_info.value.data["field"] == field


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
