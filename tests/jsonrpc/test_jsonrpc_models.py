from typing import TypeVar

import pytest
from a2a._base import A2ABaseModel

from codex_a2a.contracts.extensions import (
    SESSION_QUERY_DEFAULT_LIMIT,
    SESSION_QUERY_MAX_LIMIT,
)
from codex_a2a.jsonrpc.interrupt_params import (
    ElicitationReplyParams,
    PermissionReplyParams,
    PermissionsReplyParams,
    raise_interrupt_validation_error,
)
from codex_a2a.jsonrpc.interrupt_recovery_params import (
    InterruptRecoveryListParams,
    raise_interrupt_recovery_validation_error,
)
from codex_a2a.jsonrpc.params import (
    JsonRpcParamsValidationError,
    parse_discovery_apps_list_params,
    parse_discovery_plugin_read_params,
    parse_discovery_plugins_list_params,
    parse_discovery_skills_list_params,
    parse_discovery_watch_params,
    parse_get_session_messages_params,
    parse_list_sessions_params,
)
from codex_a2a.jsonrpc.params_common import validate_params_model
from codex_a2a.jsonrpc.review_control_params import (
    ReviewStartControlParams,
    ReviewWatchControlParams,
    raise_review_control_validation_error,
)
from codex_a2a.jsonrpc.thread_lifecycle_params import (
    ThreadArchiveControlParams,
    ThreadForkControlParams,
    ThreadMetadataUpdateControlParams,
    ThreadWatchControlParams,
    ThreadWatchReleaseControlParams,
    raise_thread_lifecycle_validation_error,
)
from codex_a2a.jsonrpc.turn_control_params import (
    TurnSteerControlParams,
    raise_turn_control_validation_error,
)

ModelT = TypeVar("ModelT", bound=A2ABaseModel)


def _parse_interrupt_reply_params(
    model_type: type[ModelT],
    payload: dict[str, object],
) -> ModelT:
    return validate_params_model(
        model_type,
        payload,
        on_error=raise_interrupt_validation_error,
    )


def _parse_interrupt_recovery_params(payload: dict[str, object]) -> InterruptRecoveryListParams:
    return validate_params_model(
        InterruptRecoveryListParams,
        payload,
        on_error=raise_interrupt_recovery_validation_error,
    )


def _parse_thread_lifecycle_params(
    model_type: type[ModelT],
    payload: dict[str, object],
) -> ModelT:
    return validate_params_model(
        model_type,
        payload,
        on_error=raise_thread_lifecycle_validation_error,
    )


def _parse_turn_control_params(payload: dict[str, object]) -> TurnSteerControlParams:
    return validate_params_model(
        TurnSteerControlParams,
        payload,
        on_error=raise_turn_control_validation_error,
    )


def _parse_review_control_params(
    model_type: type[ModelT],
    payload: dict[str, object],
) -> ModelT:
    return validate_params_model(
        model_type,
        payload,
        on_error=raise_review_control_validation_error,
    )


def test_parse_permission_reply_params_rejects_missing_reply() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        _parse_interrupt_reply_params(PermissionReplyParams, {"request_id": "perm-1"})

    assert str(exc_info.value) == "reply must be a string"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "reply"}
    assert "fields" not in exc_info.value.data


def test_parse_permissions_reply_params_accepts_scope_and_permissions_object() -> None:
    payload = _parse_interrupt_reply_params(
        PermissionsReplyParams,
        {
            "request_id": "perm-2",
            "permissions": {"fileSystem": {"write": ["/workspace"]}},
            "scope": "session",
        },
    )

    assert payload.request_id == "perm-2"
    assert payload.permissions == {"fileSystem": {"write": ["/workspace"]}}
    assert payload.scope == "session"


def test_parse_permissions_reply_params_rejects_non_object_permissions() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        _parse_interrupt_reply_params(
            PermissionsReplyParams,
            {"request_id": "perm-2", "permissions": []},
        )

    assert str(exc_info.value) == "permissions must be an object"
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "permissions"}


def test_parse_elicitation_reply_params_rejects_non_null_content_for_decline() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        _parse_interrupt_reply_params(
            ElicitationReplyParams,
            {"request_id": "eli-1", "action": "decline", "content": {"ignored": True}},
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
    payload = _parse_interrupt_recovery_params({"interrupt_type": "permissions"})

    assert payload.interrupt_type == "permissions"


def test_parse_interrupt_recovery_list_params_rejects_invalid_type() -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        _parse_interrupt_recovery_params({"interrupt_type": "unknown"})

    assert str(exc_info.value) == (
        "type must be one of: permission, question, permissions, elicitation"
    )
    assert exc_info.value.data == {"type": "INVALID_FIELD", "field": "interrupt_type"}


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
    fork = _parse_thread_lifecycle_params(
        ThreadForkControlParams,
        {
            "thread_id": "thr-1",
            "request": {"ephemeral": True},
            "metadata": {"codex": {"directory": "/workspace"}},
        },
    )
    metadata_update = _parse_thread_lifecycle_params(
        ThreadMetadataUpdateControlParams,
        {
            "thread_id": "thr-1",
            "request": {"git_info": {"branch": "feat/thread-lifecycle", "origin_url": "https://x"}},
        },
    )
    watch = _parse_thread_lifecycle_params(
        ThreadWatchControlParams,
        {
            "request": {
                "events": ["thread.started", "thread.status.changed", "thread.started"],
                "thread_ids": ["thr-1", "thr-2", "thr-1"],
            }
        },
    )
    watch_release = _parse_thread_lifecycle_params(
        ThreadWatchReleaseControlParams,
        {"task_id": "task-watch-1"},
    )

    assert fork.thread_id == "thr-1"
    assert fork.request is not None
    assert fork.request.model_dump(exclude_none=True) == {"ephemeral": True}
    assert fork.metadata is not None
    assert fork.metadata.codex is not None
    assert fork.metadata.codex.directory == "/workspace"
    assert metadata_update.request.model_dump(exclude_none=True) == {
        "git_info": {
            "branch": "feat/thread-lifecycle",
            "origin_url": "https://x",
        }
    }
    assert watch.request is not None
    assert watch.request.model_dump(by_alias=False, exclude_none=True) == {
        "events": ["thread.started", "thread.status.changed"],
        "thread_ids": ["thr-1", "thr-2"],
    }
    assert watch_release.task_id == "task-watch-1"


def test_parse_turn_and_review_control_params_use_canonical_shapes() -> None:
    steer = _parse_turn_control_params(
        {
            "thread_id": "thr-1",
            "expected_turn_id": "turn-1",
            "request": {
                "parts": [
                    {"type": "text", "text": "Focus on the failing tests first."},
                    {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
                ]
            },
        },
    )
    review = _parse_review_control_params(
        ReviewStartControlParams,
        {
            "thread_id": "thr-1",
            "delivery": "detached",
            "target": {
                "type": "commit",
                "sha": "commit-demo-123",
                "title": "Polish tui colors",
            },
        },
    )
    review_watch = _parse_review_control_params(
        ReviewWatchControlParams,
        {
            "thread_id": "thr-1",
            "review_thread_id": "thr-1-review",
            "turn_id": "turn-review-1",
            "request": {"events": ["review.started", "review.completed", "review.started"]},
        },
    )

    assert steer.thread_id == "thr-1"
    assert steer.expected_turn_id == "turn-1"
    assert steer.request.model_dump(exclude_none=True) == {
        "parts": [
            {"type": "text", "text": "Focus on the failing tests first."},
            {"type": "mention", "name": "Demo App", "path": "app://demo-app"},
        ]
    }
    assert review.thread_id == "thr-1"
    assert review.delivery == "detached"
    assert review.target.model_dump(exclude_none=True) == {
        "type": "commit",
        "sha": "commit-demo-123",
        "title": "Polish tui colors",
    }
    assert review_watch.thread_id == "thr-1"
    assert review_watch.review_thread_id == "thr-1-review"
    assert review_watch.turn_id == "turn-review-1"
    assert review_watch.request is not None
    assert review_watch.request.model_dump(exclude_none=True) == {
        "events": ["review.started", "review.completed"]
    }


@pytest.mark.parametrize(
    ("parser", "payload", "message", "field"),
    [
        (
            lambda payload: _parse_thread_lifecycle_params(ThreadArchiveControlParams, payload),
            {"thread_id": "   "},
            "Missing required params.thread_id",
            "thread_id",
        ),
        (
            lambda payload: _parse_thread_lifecycle_params(ThreadForkControlParams, payload),
            {"thread_id": "thr-1", "request": {"ephemeral": "yes"}},
            "request.ephemeral must be a boolean",
            "request.ephemeral",
        ),
        (
            lambda payload: _parse_thread_lifecycle_params(
                ThreadMetadataUpdateControlParams,
                payload,
            ),
            {"thread_id": "thr-1", "request": {"git_info": {}}},
            "request.git_info must include at least one field",
            "request.git_info",
        ),
        (
            lambda payload: _parse_thread_lifecycle_params(ThreadWatchControlParams, payload),
            {"request": {"events": ["thread.deleted"]}},
            (
                "request.events entries must be one of: thread.started, "
                "thread.status.changed, thread.archived, thread.unarchived, thread.closed"
            ),
            "request.events",
        ),
        (
            lambda payload: _parse_thread_lifecycle_params(ThreadWatchControlParams, payload),
            {"request": {"thread_ids": ["thr-1", "  "]}},
            "request.thread_ids[] must be a non-empty string",
            "request.thread_ids",
        ),
        (
            lambda payload: _parse_thread_lifecycle_params(
                ThreadWatchReleaseControlParams,
                payload,
            ),
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
            _parse_turn_control_params,
            {
                "thread_id": "thr-1",
                "expected_turn_id": "turn-1",
                "request": {"parts": []},
            },
            "request.parts must be a non-empty array",
            "request.parts",
        ),
        (
            _parse_turn_control_params,
            {
                "thread_id": "thr-1",
                "expected_turn_id": "turn-1",
                "request": {"parts": [{"type": "file", "path": "/tmp/x"}]},
            },
            "request.parts[].type must be one of: text, image, mention, skill",
            "request.parts[0].type",
        ),
        (
            lambda payload: _parse_review_control_params(ReviewStartControlParams, payload),
            {"thread_id": "thr-1", "delivery": "queued", "target": {"type": "commit", "sha": "a"}},
            "delivery must be one of: inline, detached",
            "delivery",
        ),
        (
            lambda payload: _parse_review_control_params(ReviewStartControlParams, payload),
            {"thread_id": "thr-1", "target": {"type": "baseBranch"}},
            "target.branch must be a non-empty string",
            "target.branch",
        ),
        (
            lambda payload: _parse_review_control_params(ReviewStartControlParams, payload),
            {"thread_id": "thr-1", "target": {"type": "custom", "instructions": "   "}},
            "target.instructions must be a non-empty string",
            "target.instructions",
        ),
        (
            lambda payload: _parse_review_control_params(ReviewWatchControlParams, payload),
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
            lambda payload: _parse_review_control_params(ReviewWatchControlParams, payload),
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


def test_parse_discovery_params_use_canonical_shapes() -> None:
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
        "force_reload": True,
        "per_cwd_extra_user_roots": [
            {
                "cwd": "/workspace/project",
                "extra_user_roots": ["/workspace/shared-skills"],
            }
        ],
    }
    assert apps == {"limit": 20, "thread_id": "thr-1", "force_refetch": False}
    assert plugins == {
        "cwds": ["/workspace/project"],
        "force_remote_sync": True,
    }
    assert plugin == {
        "marketplace_path": "/workspace/project/.codex/plugins/marketplace.json",
        "plugin_name": "sample",
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
            {"marketplace_path": "", "plugin_name": "sample"},
            "marketplace_path",
        ),
    ],
)
def test_parse_discovery_params_reject_invalid_fields(parser, payload, field: str) -> None:
    with pytest.raises(JsonRpcParamsValidationError) as exc_info:
        parser(payload)

    assert exc_info.value.data["field"] == field
