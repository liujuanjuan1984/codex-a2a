from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2a.server.apps.jsonrpc.jsonrpc_app import JSONRPCApplication

from codex_a2a.contracts.runtime_output import (
    build_artifact_stream_contract_params,
    build_interrupt_contract_params,
    build_session_contract_params,
    build_status_stream_contract_params,
    build_usage_contract_params,
)
from codex_a2a.execution.request_overrides import request_execution_options_fields
from codex_a2a.execution.tool_call_payloads import build_tool_call_payload_contract_params
from codex_a2a.profile.runtime import RuntimeProfile

COMPATIBILITY_PROFILE_EXTENSION_URI = "urn:codex-a2a:compatibility-profile/v1"
WIRE_CONTRACT_EXTENSION_URI = "urn:codex-a2a:wire-contract/v1"
SESSION_BINDING_EXTENSION_URI = "urn:a2a:session-binding/v1"
STREAMING_EXTENSION_URI = "urn:a2a:stream-hints/v1"
SESSION_QUERY_EXTENSION_URI = "urn:codex-a2a:codex-session-query/v1"
DISCOVERY_EXTENSION_URI = "urn:codex-a2a:codex-discovery/v1"
THREAD_LIFECYCLE_EXTENSION_URI = "urn:codex-a2a:codex-thread-lifecycle/v1"
TURN_CONTROL_EXTENSION_URI = "urn:codex-a2a:codex-turn-control/v1"
REVIEW_CONTROL_EXTENSION_URI = "urn:codex-a2a:codex-review/v1"
EXEC_CONTROL_EXTENSION_URI = "urn:codex-a2a:codex-exec/v1"
INTERRUPT_CALLBACK_EXTENSION_URI = "urn:a2a:interactive-interrupt/v1"

TASKS_RESUBSCRIBE_METHOD = "tasks/resubscribe"
TASKS_SUBSCRIBE_HTTP_ENDPOINT = "/v1/tasks/{id}:subscribe"

SHARED_SESSION_BINDING_FIELD = "metadata.shared.session.id"
SHARED_SESSION_METADATA_FIELD = "metadata.shared.session"
SHARED_STREAM_METADATA_FIELD = "metadata.shared.stream"
SHARED_INTERRUPT_METADATA_FIELD = "metadata.shared.interrupt"
SHARED_USAGE_METADATA_FIELD = "metadata.shared.usage"
CODEX_DIRECTORY_METADATA_FIELD = "metadata.codex.directory"
CODEX_EXECUTION_METADATA_FIELD = "metadata.codex.execution"

_REQUEST_EXECUTION_PROVIDER_METADATA = ["codex.directory", "codex.execution"]


def _build_request_execution_options_contract() -> dict[str, Any]:
    return {
        "metadata_field": CODEX_EXECUTION_METADATA_FIELD,
        "fields": request_execution_options_fields(),
        "persists_for_thread": True,
        "notes": [
            (
                "execution.model, execution.effort, execution.summary, and "
                "execution.personality map to upstream thread/start or turn/start "
                "overrides when the selected method starts or continues a turn."
            ),
            (
                "directory remains a separate metadata.codex.directory override so "
                "existing clients do not need to migrate cwd handling."
            ),
        ],
    }


@dataclass(frozen=True)
class SessionQueryMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    unsupported_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    items_type: str | None = None
    items_field: str | None = None
    notification_response_status: int | None = None
    pagination_mode: str | None = None
    execution_binding: str | None = None
    session_binding: str | None = None
    uses_upstream_session_context: bool | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterruptMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    notification_response_status: int | None = None


@dataclass(frozen=True)
class ExecMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    notification_response_status: int | None = None
    execution_binding: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    items_type: str | None = None
    items_field: str | None = None
    notification_response_status: int | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadLifecycleMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    notification_response_status: int | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnControlMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    unsupported_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    notification_response_status: int | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewControlMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    unsupported_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    notification_response_status: int | None = None
    notes: tuple[str, ...] = ()


SESSION_QUERY_PAGINATION_MODE = "limit"
SESSION_QUERY_PAGINATION_BEHAVIOR = "mixed"
SESSION_QUERY_DEFAULT_LIMIT = 20
SESSION_QUERY_MAX_LIMIT = 100
SESSION_QUERY_PAGINATION_PARAMS: tuple[str, ...] = ("limit",)
SESSION_QUERY_PAGINATION_UNSUPPORTED: tuple[str, ...] = ("cursor", "page", "size")

SESSION_QUERY_METHOD_CONTRACTS: dict[str, SessionQueryMethodContract] = {
    "list_sessions": SessionQueryMethodContract(
        method="codex.sessions.list",
        optional_params=("limit", "query.limit"),
        unsupported_params=SESSION_QUERY_PAGINATION_UNSUPPORTED,
        result_fields=("items",),
        items_type="Task[]",
        items_field="items",
        notification_response_status=204,
        pagination_mode=SESSION_QUERY_PAGINATION_MODE,
    ),
    "get_session_messages": SessionQueryMethodContract(
        method="codex.sessions.messages.list",
        required_params=("session_id",),
        optional_params=("limit", "query.limit"),
        unsupported_params=SESSION_QUERY_PAGINATION_UNSUPPORTED,
        result_fields=("items",),
        items_type="Message[]",
        items_field="items",
        notification_response_status=204,
        pagination_mode=SESSION_QUERY_PAGINATION_MODE,
    ),
    "prompt_async": SessionQueryMethodContract(
        method="codex.sessions.prompt_async",
        required_params=("session_id", "request.parts"),
        optional_params=(
            "request.messageID",
            "request.agent",
            "request.system",
            "request.variant",
            CODEX_DIRECTORY_METADATA_FIELD,
            CODEX_EXECUTION_METADATA_FIELD,
        ),
        result_fields=("ok", "session_id", "turn_id"),
        notification_response_status=204,
        notes=(
            (
                "request.parts supports structured rich input items with type=text, "
                "image, mention, and skill."
            ),
            (
                "image parts map to upstream input_image. URL forms pass through "
                "directly; bytes forms are converted to data URLs."
            ),
            (
                "This contract does not currently declare upstream local_image; "
                "mention and skill paths are forwarded verbatim."
            ),
        ),
    ),
    "command": SessionQueryMethodContract(
        method="codex.sessions.command",
        required_params=("session_id", "request.command"),
        optional_params=(
            "request.arguments",
            "request.messageID",
            CODEX_DIRECTORY_METADATA_FIELD,
            CODEX_EXECUTION_METADATA_FIELD,
        ),
        result_fields=("item",),
        notification_response_status=204,
    ),
    "shell": SessionQueryMethodContract(
        method="codex.sessions.shell",
        required_params=("session_id", "request.command"),
        optional_params=(CODEX_DIRECTORY_METADATA_FIELD,),
        result_fields=("item",),
        notification_response_status=204,
        execution_binding="standalone_command_exec",
        session_binding="ownership_attribution_only",
        uses_upstream_session_context=False,
        notes=(
            (
                "Shell requests run through Codex command/exec and do not resume or "
                "create an upstream thread."
            ),
            (
                "session_id is used for ownership checks and A2A result attribution; "
                "it does not provide an upstream session-bound shell context."
            ),
            (
                "This method returns a one-shot shell snapshot and does not expose "
                "interactive PTY lifecycle operations such as write, resize, or "
                "terminate."
            ),
        ),
    ),
}

SESSION_QUERY_METHODS: dict[str, str] = {
    key: contract.method for key, contract in SESSION_QUERY_METHOD_CONTRACTS.items()
}
SESSION_CONTROL_METHOD_KEYS: tuple[str, ...] = ("prompt_async", "command", "shell")
SESSION_CONTROL_METHODS: dict[str, str] = {
    key: SESSION_QUERY_METHODS[key] for key in SESSION_CONTROL_METHOD_KEYS
}

SESSION_QUERY_ERROR_BUSINESS_CODES: dict[str, int] = {
    "SESSION_NOT_FOUND": -32001,
    "SESSION_FORBIDDEN": -32006,
    "AUTHORIZATION_FORBIDDEN": -32007,
    "UPSTREAM_UNREACHABLE": -32002,
    "UPSTREAM_HTTP_ERROR": -32003,
    "UPSTREAM_PAYLOAD_ERROR": -32005,
}
SESSION_QUERY_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "capability",
    "required_principal",
    "session_id",
    "upstream_status",
    "detail",
)
SESSION_QUERY_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
    "supported",
    "unsupported",
)

DISCOVERY_METHOD_CONTRACTS: dict[str, DiscoveryMethodContract] = {
    "list_skills": DiscoveryMethodContract(
        method="codex.discovery.skills.list",
        optional_params=("cwds", "force_reload", "per_cwd_extra_user_roots"),
        result_fields=("items",),
        items_type="DiscoverySkillScope[]",
        items_field="items",
        notification_response_status=204,
        notes=(
            (
                "Each item represents one cwd scope and includes normalized skill entries "
                "with stable fields plus codex.raw passthrough payloads."
            ),
            (
                "Use item.skills[].path directly when constructing rich-input skill items "
                "for codex.sessions.prompt_async or core A2A DataPart payloads."
            ),
        ),
    ),
    "list_apps": DiscoveryMethodContract(
        method="codex.discovery.apps.list",
        optional_params=("cursor", "limit", "thread_id", "force_refetch"),
        result_fields=("items", "next_cursor"),
        items_type="DiscoveryApp[]",
        items_field="items",
        notification_response_status=204,
        notes=(
            (
                "Use item.mention_path directly when constructing rich-input mention items "
                "for app invocation."
            ),
        ),
    ),
    "list_plugins": DiscoveryMethodContract(
        method="codex.discovery.plugins.list",
        optional_params=("cwds", "force_remote_sync"),
        result_fields=(
            "items",
            "featured_plugin_ids",
            "marketplace_load_errors",
            "remote_sync_error",
        ),
        items_type="DiscoveryPluginMarketplace[]",
        items_field="items",
        notification_response_status=204,
        notes=(
            (
                "plugin/list remains upstream experimental; this contract exposes a stable "
                "minimum subset plus codex.raw passthrough payloads."
            ),
            (
                "Use plugin summaries' mention_path directly when constructing rich-input "
                "mention items for plugin invocation."
            ),
        ),
    ),
    "read_plugin": DiscoveryMethodContract(
        method="codex.discovery.plugins.read",
        required_params=("marketplace_path", "plugin_name"),
        result_fields=("item",),
        notification_response_status=204,
        notes=(
            (
                "plugin/read remains upstream experimental; this contract exposes a stable "
                "minimum subset plus codex.raw passthrough payloads."
            ),
        ),
    ),
    "watch": DiscoveryMethodContract(
        method="codex.discovery.watch",
        optional_params=("request.events",),
        result_fields=("ok", "task_id", "context_id"),
        notification_response_status=204,
        notes=(
            (
                "Use this method to bridge upstream skills/changed and app/list/updated "
                "notifications into the normal A2A task stream."
            ),
            (
                "Watch results are delivered through tasks/resubscribe as DataPart payloads "
                "with kind=skills_changed or kind=apps_updated."
            ),
        ),
    ),
}

DISCOVERY_METHODS: dict[str, str] = {
    key: contract.method for key, contract in DISCOVERY_METHOD_CONTRACTS.items()
}

DISCOVERY_ERROR_BUSINESS_CODES: dict[str, int] = {
    "UPSTREAM_UNREACHABLE": -32002,
    "UPSTREAM_HTTP_ERROR": -32003,
    "UPSTREAM_PAYLOAD_ERROR": -32005,
}
DISCOVERY_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "upstream_status",
    "detail",
)
DISCOVERY_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
)

THREAD_LIFECYCLE_SUPPORTED_EVENTS: tuple[str, ...] = (
    "thread.started",
    "thread.status.changed",
    "thread.archived",
    "thread.unarchived",
    "thread.closed",
)
THREAD_LIFECYCLE_METHOD_CONTRACTS: dict[str, ThreadLifecycleMethodContract] = {
    "fork": ThreadLifecycleMethodContract(
        method="codex.threads.fork",
        required_params=("thread_id",),
        optional_params=("request.ephemeral", CODEX_DIRECTORY_METADATA_FIELD),
        result_fields=("ok", "thread", "thread_id"),
        notification_response_status=204,
        notes=(
            (
                "Fork creates a new upstream thread id and returns a normalized minimal "
                "thread projection plus codex.raw passthrough data."
            ),
            ("request.ephemeral forwards to upstream thread/fork ephemeral mode when true."),
        ),
    ),
    "archive": ThreadLifecycleMethodContract(
        method="codex.threads.archive",
        required_params=("thread_id",),
        optional_params=(CODEX_DIRECTORY_METADATA_FIELD,),
        result_fields=("ok", "thread_id"),
        notification_response_status=204,
        notes=(
            (
                "Archive returns only a minimal stable success envelope; clients should use "
                "codex.threads.watch for lifecycle notifications."
            ),
        ),
    ),
    "unarchive": ThreadLifecycleMethodContract(
        method="codex.threads.unarchive",
        required_params=("thread_id",),
        optional_params=(CODEX_DIRECTORY_METADATA_FIELD,),
        result_fields=("ok", "thread", "thread_id"),
        notification_response_status=204,
        notes=(
            (
                "Unarchive restores a persisted rollout and returns a normalized minimal "
                "thread projection plus codex.raw passthrough data."
            ),
        ),
    ),
    "metadata_update": ThreadLifecycleMethodContract(
        method="codex.threads.metadata.update",
        required_params=("thread_id", "request.git_info"),
        optional_params=(
            "request.git_info.sha",
            "request.git_info.branch",
            "request.git_info.origin_url",
            CODEX_DIRECTORY_METADATA_FIELD,
        ),
        result_fields=("ok", "thread", "thread_id"),
        notification_response_status=204,
        notes=(
            (
                "This surface currently stabilizes only persisted git_info updates. "
                "Explicit null clears a stored field; omitted fields are left unchanged."
            ),
        ),
    ),
    "watch": ThreadLifecycleMethodContract(
        method="codex.threads.watch",
        optional_params=("request.events", "request.thread_ids", CODEX_DIRECTORY_METADATA_FIELD),
        result_fields=("ok", "task_id", "context_id"),
        notification_response_status=204,
        notes=(
            (
                "Use tasks/resubscribe to consume lifecycle events emitted through the watch "
                "task stream."
            ),
            ("request.thread_ids narrows the watch to specific upstream thread ids when provided."),
            ("Use codex.threads.watch.release with the returned task_id to stop an owned watch."),
        ),
    ),
    "watch_release": ThreadLifecycleMethodContract(
        method="codex.threads.watch.release",
        required_params=("task_id",),
        result_fields=(
            "ok",
            "task_id",
            "owner_status",
            "release_reason",
            "subscription_key",
            "remaining_owner_count",
            "subscription_released",
        ),
        notification_response_status=204,
        notes=(
            (
                "Release a previously-started codex.threads.watch task by the task_id returned "
                "from watch creation."
            ),
            (
                "This method releases ownership-scoped local watch state; it does not expose raw "
                "upstream thread/unsubscribe."
            ),
        ),
    ),
}
THREAD_LIFECYCLE_METHODS: dict[str, str] = {
    key: contract.method for key, contract in THREAD_LIFECYCLE_METHOD_CONTRACTS.items()
}
THREAD_LIFECYCLE_ERROR_BUSINESS_CODES: dict[str, int] = {
    "THREAD_NOT_FOUND": -32010,
    "THREAD_FORBIDDEN": -32011,
    "WATCH_NOT_FOUND": -32014,
    "WATCH_FORBIDDEN": -32015,
    "UPSTREAM_UNREACHABLE": -32002,
    "UPSTREAM_HTTP_ERROR": -32003,
}
THREAD_LIFECYCLE_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "thread_id",
    "task_id",
    "upstream_status",
    "detail",
)
THREAD_LIFECYCLE_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
)

TURN_CONTROL_METHOD_CONTRACTS: dict[str, TurnControlMethodContract] = {
    "steer": TurnControlMethodContract(
        method="codex.turns.steer",
        required_params=("thread_id", "expected_turn_id", "request.parts"),
        unsupported_params=(
            "metadata",
            CODEX_DIRECTORY_METADATA_FIELD,
            CODEX_EXECUTION_METADATA_FIELD,
            "request.agent",
            "request.system",
            "request.variant",
            "request.messageID",
        ),
        result_fields=("ok", "thread_id", "turn_id"),
        notification_response_status=204,
        notes=(
            (
                "Steering appends input to the currently active regular turn without "
                "creating a new turn."
            ),
            (
                "request.parts accepts the same rich input item types as "
                "codex.sessions.prompt_async, but turn-level overrides are intentionally "
                "not accepted on this surface."
            ),
            (
                "Upstream rejects steering when there is no active turn, expected_turn_id "
                "does not match, or the active turn kind does not accept same-turn input."
            ),
        ),
    ),
}
TURN_CONTROL_METHODS: dict[str, str] = {
    key: contract.method for key, contract in TURN_CONTROL_METHOD_CONTRACTS.items()
}
TURN_CONTROL_ERROR_BUSINESS_CODES: dict[str, int] = {
    "TURN_NOT_STEERABLE": -32012,
    "TURN_FORBIDDEN": -32013,
}
TURN_CONTROL_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "thread_id",
    "expected_turn_id",
    "upstream_code",
    "detail",
)
TURN_CONTROL_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
)

REVIEW_CONTROL_SUPPORTED_EVENTS: tuple[str, ...] = (
    "review.started",
    "review.status.changed",
    "review.completed",
    "review.failed",
)
REVIEW_CONTROL_METHOD_CONTRACTS: dict[str, ReviewControlMethodContract] = {
    "start": ReviewControlMethodContract(
        method="codex.review.start",
        required_params=("thread_id", "target.type"),
        optional_params=(
            "delivery",
            "target.branch",
            "target.sha",
            "target.title",
            "target.instructions",
        ),
        unsupported_params=(
            "metadata",
            CODEX_DIRECTORY_METADATA_FIELD,
            CODEX_EXECUTION_METADATA_FIELD,
        ),
        result_fields=("ok", "turn_id", "review_thread_id"),
        notification_response_status=204,
        notes=(
            (
                "Supported targets are uncommittedChanges, baseBranch, commit, and custom. "
                "Target shapes intentionally mirror the upstream app-server review/start "
                "schema."
            ),
            (
                "delivery defaults to inline. detached forks a new review thread and "
                "returns its review_thread_id."
            ),
            (
                "Use codex.review.watch when you need a stable task-stream bridge for "
                "review lifecycle observation."
            ),
            (
                "review/start is a control-handle surface. It returns turn_id and "
                "review_thread_id, not the spawned review turn payload."
            ),
        ),
    ),
    "watch": ReviewControlMethodContract(
        method="codex.review.watch",
        required_params=("thread_id", "review_thread_id", "turn_id"),
        optional_params=("request.events",),
        unsupported_params=(
            "metadata",
            CODEX_DIRECTORY_METADATA_FIELD,
            CODEX_EXECUTION_METADATA_FIELD,
        ),
        result_fields=("ok", "task_id", "context_id"),
        notification_response_status=204,
        notes=(
            (
                "review.started is emitted locally from the supplied watch handle because "
                "review/watch is normally called after review/start already returned."
            ),
            (
                "review.status.changed is a coarse-grained projection of upstream "
                "thread/status/changed notifications for the watched review thread."
            ),
            (
                "review.completed and review.failed are derived from the watched "
                "turn/completed notification for the supplied turn_id."
            ),
        ),
    ),
}
REVIEW_CONTROL_METHODS: dict[str, str] = {
    key: contract.method for key, contract in REVIEW_CONTROL_METHOD_CONTRACTS.items()
}
REVIEW_CONTROL_ERROR_BUSINESS_CODES: dict[str, int] = {
    "REVIEW_FORBIDDEN": -32016,
    "REVIEW_REJECTED": -32017,
}
REVIEW_CONTROL_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "thread_id",
    "upstream_code",
    "detail",
)
REVIEW_CONTROL_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
)

INTERRUPT_CALLBACK_METHOD_CONTRACTS: dict[str, InterruptMethodContract] = {
    "reply_permission": InterruptMethodContract(
        method="a2a.interrupt.permission.reply",
        required_params=("request_id", "reply"),
        optional_params=("message", "metadata"),
        notification_response_status=204,
    ),
    "reply_question": InterruptMethodContract(
        method="a2a.interrupt.question.reply",
        required_params=("request_id", "answers"),
        optional_params=("metadata",),
        notification_response_status=204,
    ),
    "reject_question": InterruptMethodContract(
        method="a2a.interrupt.question.reject",
        required_params=("request_id",),
        optional_params=("metadata",),
        notification_response_status=204,
    ),
    "reply_permissions": InterruptMethodContract(
        method="a2a.interrupt.permissions.reply",
        required_params=("request_id", "permissions"),
        optional_params=("scope", "metadata"),
        notification_response_status=204,
    ),
    "reply_elicitation": InterruptMethodContract(
        method="a2a.interrupt.elicitation.reply",
        required_params=("request_id", "action"),
        optional_params=("content", "metadata"),
        notification_response_status=204,
    ),
}

INTERRUPT_CALLBACK_METHODS: dict[str, str] = {
    key: contract.method for key, contract in INTERRUPT_CALLBACK_METHOD_CONTRACTS.items()
}

EXEC_CONTROL_METHOD_CONTRACTS: dict[str, ExecMethodContract] = {
    "exec_start": ExecMethodContract(
        method="codex.exec.start",
        required_params=("request.command",),
        optional_params=(
            "request.arguments",
            "request.process_id",
            "request.tty",
            "request.rows",
            "request.cols",
            "request.output_bytes_cap",
            "request.disable_output_cap",
            "request.timeout_ms",
            "request.disable_timeout",
            CODEX_DIRECTORY_METADATA_FIELD,
        ),
        result_fields=("ok", "task_id", "context_id", "process_id"),
        notification_response_status=204,
        execution_binding="standalone_interactive_command_exec",
        notes=(
            (
                "codex.exec.start begins a standalone interactive command/exec session and "
                "returns immediately with process/task handles."
            ),
            (
                "Output is delivered through the normal A2A task stream and "
                "tasks/resubscribe surfaces rather than the JSON-RPC response body."
            ),
            (
                "This surface is intentionally separate from codex.sessions.shell, which "
                "remains a one-shot shell snapshot contract."
            ),
        ),
    ),
    "exec_write": ExecMethodContract(
        method="codex.exec.write",
        required_params=("request.process_id",),
        optional_params=("request.delta_base64", "request.close_stdin"),
        result_fields=("ok", "process_id"),
        notification_response_status=204,
        execution_binding="standalone_interactive_command_exec",
    ),
    "exec_resize": ExecMethodContract(
        method="codex.exec.resize",
        required_params=("request.process_id", "request.rows", "request.cols"),
        result_fields=("ok", "process_id"),
        notification_response_status=204,
        execution_binding="standalone_interactive_command_exec",
    ),
    "exec_terminate": ExecMethodContract(
        method="codex.exec.terminate",
        required_params=("request.process_id",),
        result_fields=("ok", "process_id"),
        notification_response_status=204,
        execution_binding="standalone_interactive_command_exec",
    ),
}

EXEC_CONTROL_METHODS: dict[str, str] = {
    key: contract.method for key, contract in EXEC_CONTROL_METHOD_CONTRACTS.items()
}

EXEC_CONTROL_ERROR_BUSINESS_CODES: dict[str, int] = {
    "AUTHORIZATION_FORBIDDEN": -32007,
    "EXEC_SESSION_NOT_FOUND": -32009,
    "EXEC_FORBIDDEN": -32018,
    "UPSTREAM_UNREACHABLE": -32002,
    "UPSTREAM_HTTP_ERROR": -32003,
}
EXEC_CONTROL_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "capability",
    "required_principal",
    "process_id",
    "upstream_status",
    "detail",
)
EXEC_CONTROL_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
)

INTERRUPT_SUCCESS_RESULT_FIELDS: tuple[str, ...] = ("ok", "request_id")
INTERRUPT_ERROR_BUSINESS_CODES: dict[str, int] = {
    "INTERRUPT_REQUEST_NOT_FOUND": -32004,
    "INTERRUPT_REQUEST_EXPIRED": -32007,
    "INTERRUPT_TYPE_MISMATCH": -32008,
    "UPSTREAM_UNREACHABLE": -32002,
    "UPSTREAM_HTTP_ERROR": -32003,
}
INTERRUPT_ERROR_TYPES: tuple[str, ...] = (
    "INTERRUPT_REQUEST_NOT_FOUND",
    "INTERRUPT_REQUEST_EXPIRED",
    "INTERRUPT_TYPE_MISMATCH",
    "UPSTREAM_UNREACHABLE",
    "UPSTREAM_HTTP_ERROR",
)
INTERRUPT_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "request_id",
    "expected_interrupt_type",
    "actual_interrupt_type",
    "upstream_status",
)
INTERRUPT_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "field",
    "fields",
    "request_id",
)

CORE_JSONRPC_METHODS: tuple[str, ...] = tuple(JSONRPCApplication.METHOD_TO_MODEL)
CORE_HTTP_ENDPOINTS: tuple[str, ...] = (
    "POST /v1/message:send",
    "POST /v1/message:stream",
    "GET /v1/tasks",
    "GET /v1/tasks/{id}",
    "POST /v1/tasks/{id}:cancel",
    "GET /v1/tasks/{id}:subscribe",
    "GET /v1/tasks/{id}/pushNotificationConfigs",
    "POST /v1/tasks/{id}/pushNotificationConfigs",
    "GET /v1/tasks/{id}/pushNotificationConfigs/{push_id}",
    "GET /v1/card",
)
WIRE_CONTRACT_UNSUPPORTED_METHOD_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "supported_methods",
    "protocol_version",
)


@dataclass(frozen=True)
class CapabilitySnapshot:
    supported_jsonrpc_methods: tuple[str, ...]
    extension_jsonrpc_methods: tuple[str, ...]
    session_query_method_keys: tuple[str, ...]
    session_query_methods: tuple[str, ...]
    discovery_methods: tuple[str, ...]
    thread_lifecycle_methods: tuple[str, ...]
    turn_control_methods: tuple[str, ...]
    review_control_methods: tuple[str, ...]
    exec_control_methods: tuple[str, ...]
    conditional_methods: dict[str, dict[str, str]]


def build_capability_snapshot(*, runtime_profile: RuntimeProfile) -> CapabilitySnapshot:
    session_query_method_keys = [
        "list_sessions",
        "get_session_messages",
        "prompt_async",
        "command",
    ]
    conditional_methods: dict[str, dict[str, str]] = {}
    if runtime_profile.session_shell_enabled:
        session_query_method_keys.append("shell")
    else:
        conditional_methods[SESSION_CONTROL_METHODS["shell"]] = {
            "reason": "disabled_by_configuration",
            "toggle": "A2A_ENABLE_SESSION_SHELL",
        }
    session_query_methods = tuple(SESSION_QUERY_METHODS[key] for key in session_query_method_keys)
    discovery_methods = tuple(DISCOVERY_METHODS.values())
    thread_lifecycle_methods = tuple(THREAD_LIFECYCLE_METHODS.values())
    if runtime_profile.turn_control_enabled:
        turn_control_methods = tuple(TURN_CONTROL_METHODS.values())
    else:
        turn_control_methods = ()
        for method in TURN_CONTROL_METHODS.values():
            conditional_methods[method] = {
                "reason": "disabled_by_configuration",
                "toggle": "A2A_ENABLE_TURN_CONTROL",
            }
    if runtime_profile.review_control_enabled:
        review_control_methods = tuple(REVIEW_CONTROL_METHODS.values())
    else:
        review_control_methods = ()
        for method in REVIEW_CONTROL_METHODS.values():
            conditional_methods[method] = {
                "reason": "disabled_by_configuration",
                "toggle": "A2A_ENABLE_REVIEW_CONTROL",
            }
    if runtime_profile.exec_control_enabled:
        exec_control_methods = tuple(EXEC_CONTROL_METHODS.values())
    else:
        exec_control_methods = ()
        for method in EXEC_CONTROL_METHODS.values():
            conditional_methods[method] = {
                "reason": "disabled_by_configuration",
                "toggle": "A2A_ENABLE_EXEC_CONTROL",
            }
    extension_jsonrpc_methods = (
        *session_query_methods,
        *discovery_methods,
        *thread_lifecycle_methods,
        *turn_control_methods,
        *review_control_methods,
        *exec_control_methods,
        *INTERRUPT_CALLBACK_METHODS.values(),
    )
    return CapabilitySnapshot(
        supported_jsonrpc_methods=(
            *CORE_JSONRPC_METHODS,
            *extension_jsonrpc_methods,
        ),
        extension_jsonrpc_methods=extension_jsonrpc_methods,
        session_query_method_keys=tuple(session_query_method_keys),
        session_query_methods=session_query_methods,
        discovery_methods=discovery_methods,
        thread_lifecycle_methods=thread_lifecycle_methods,
        turn_control_methods=turn_control_methods,
        review_control_methods=review_control_methods,
        exec_control_methods=exec_control_methods,
        conditional_methods=conditional_methods,
    )


def build_wire_contract_extension_params(
    *,
    protocol_version: str,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    resubscribe_behavior = {
        "scope": "service-level",
        "jsonrpc_method": TASKS_RESUBSCRIBE_METHOD,
        "http_endpoint": TASKS_SUBSCRIBE_HTTP_ENDPOINT,
        "non_terminal_behavior": "stream_live_updates",
        "terminal_behavior": "replay_once_then_close",
        "notes": [
            (
                "tasks/resubscribe remains part of the core A2A method baseline, but this "
                "deployment's terminal-task replay behavior is a service-level contract."
            ),
            (
                "When the task is already terminal, this service replays one final task "
                "snapshot and then closes the stream."
            ),
        ],
    }
    return {
        "protocol_version": protocol_version,
        "preferred_transport": "HTTP+JSON",
        "additional_transports": ["JSON-RPC"],
        "core": {
            "jsonrpc_methods": list(CORE_JSONRPC_METHODS),
            "http_endpoints": list(CORE_HTTP_ENDPOINTS),
        },
        "extensions": {
            "jsonrpc_methods": list(snapshot.extension_jsonrpc_methods),
            "conditionally_available_methods": dict(snapshot.conditional_methods),
            "extension_uris": [
                SESSION_BINDING_EXTENSION_URI,
                STREAMING_EXTENSION_URI,
                SESSION_QUERY_EXTENSION_URI,
                DISCOVERY_EXTENSION_URI,
                THREAD_LIFECYCLE_EXTENSION_URI,
                TURN_CONTROL_EXTENSION_URI,
                REVIEW_CONTROL_EXTENSION_URI,
                EXEC_CONTROL_EXTENSION_URI,
                INTERRUPT_CALLBACK_EXTENSION_URI,
            ],
        },
        "all_jsonrpc_methods": list(snapshot.supported_jsonrpc_methods),
        "unsupported_method_error": {
            "code": -32601,
            "type": "METHOD_NOT_SUPPORTED",
            "data_fields": list(WIRE_CONTRACT_UNSUPPORTED_METHOD_DATA_FIELDS),
        },
        "service_behaviors": {
            TASKS_RESUBSCRIBE_METHOD: resubscribe_behavior,
        },
    }


def build_compatibility_profile_params(
    *,
    protocol_version: str,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    resubscribe_behavior = {
        "scope": "service-level",
        "jsonrpc_method": TASKS_RESUBSCRIBE_METHOD,
        "http_endpoint": TASKS_SUBSCRIBE_HTTP_ENDPOINT,
        "non_terminal_behavior": "stream_live_updates",
        "terminal_behavior": "replay_once_then_close",
        "notes": [
            (
                "tasks/resubscribe itself is part of the core interoperability baseline, but "
                "the terminal replay-once policy is deployment-specific service behavior."
            ),
            (
                "Consumers should not assume replay-once terminal delivery is guaranteed by "
                "generic A2A runtimes unless it is declared explicitly."
            ),
        ],
    }

    method_retention: dict[str, dict[str, Any]] = {
        method: {
            "surface": "core",
            "availability": "always",
            "retention": "required",
        }
        for method in CORE_JSONRPC_METHODS
    }
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": "always",
                "retention": "stable",
                "extension_uri": DISCOVERY_EXTENSION_URI,
            }
            for method in snapshot.discovery_methods
        }
    )
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": "always",
                "retention": "stable",
                "extension_uri": THREAD_LIFECYCLE_EXTENSION_URI,
            }
            for method in snapshot.thread_lifecycle_methods
        }
    )
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": runtime_profile.turn_control.availability,
                "retention": "deployment-conditional",
                "extension_uri": TURN_CONTROL_EXTENSION_URI,
                "toggle": runtime_profile.turn_control.toggle,
            }
            for method in TURN_CONTROL_METHODS.values()
        }
    )
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": runtime_profile.review_control.availability,
                "retention": "deployment-conditional",
                "extension_uri": REVIEW_CONTROL_EXTENSION_URI,
                "toggle": runtime_profile.review_control.toggle,
            }
            for method in REVIEW_CONTROL_METHODS.values()
        }
    )
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": "always",
                "retention": "stable",
                "extension_uri": SESSION_QUERY_EXTENSION_URI,
            }
            for method in snapshot.session_query_methods
        }
    )
    method_retention[SESSION_CONTROL_METHODS["shell"]] = {
        "surface": "extension",
        "availability": ("enabled" if runtime_profile.session_shell_enabled else "disabled"),
        "retention": "deployment-conditional",
        "extension_uri": SESSION_QUERY_EXTENSION_URI,
        "toggle": "A2A_ENABLE_SESSION_SHELL",
    }
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": runtime_profile.exec_control.availability,
                "retention": "deployment-conditional",
                "extension_uri": EXEC_CONTROL_EXTENSION_URI,
                "toggle": runtime_profile.exec_control.toggle,
            }
            for method in EXEC_CONTROL_METHODS.values()
        }
    )
    method_retention.update(
        {
            method: {
                "surface": "extension",
                "availability": "always",
                "retention": "stable",
                "extension_uri": INTERRUPT_CALLBACK_EXTENSION_URI,
            }
            for method in INTERRUPT_CALLBACK_METHODS.values()
        }
    )

    extension_retention = {
        SESSION_BINDING_EXTENSION_URI: {
            "surface": "core-runtime-metadata",
            "availability": "always",
            "retention": "required",
        },
        STREAMING_EXTENSION_URI: {
            "surface": "core-runtime-metadata",
            "availability": "always",
            "retention": "required",
        },
        SESSION_QUERY_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": "always",
            "retention": "stable",
        },
        DISCOVERY_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": "always",
            "retention": "stable",
        },
        THREAD_LIFECYCLE_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": "always",
            "retention": "stable",
        },
        TURN_CONTROL_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": runtime_profile.turn_control.availability,
            "retention": "deployment-conditional",
            "toggle": runtime_profile.turn_control.toggle,
        },
        REVIEW_CONTROL_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": runtime_profile.review_control.availability,
            "retention": "deployment-conditional",
            "toggle": runtime_profile.review_control.toggle,
        },
        EXEC_CONTROL_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": runtime_profile.exec_control.availability,
            "retention": "deployment-conditional",
            "toggle": runtime_profile.exec_control.toggle,
        },
        INTERRUPT_CALLBACK_EXTENSION_URI: {
            "surface": "jsonrpc-extension",
            "availability": "always",
            "retention": "stable",
        },
    }

    return {
        "profile_id": runtime_profile.profile_id,
        "protocol_version": protocol_version,
        "deployment": runtime_profile.deployment.as_dict(),
        "runtime_features": runtime_profile.runtime_features_dict(),
        "core": {
            "jsonrpc_methods": list(CORE_JSONRPC_METHODS),
            "http_endpoints": list(CORE_HTTP_ENDPOINTS),
        },
        "service_behaviors": {
            TASKS_RESUBSCRIBE_METHOD: resubscribe_behavior,
        },
        "extension_taxonomy": {
            "shared_extensions": [
                SESSION_BINDING_EXTENSION_URI,
                STREAMING_EXTENSION_URI,
                INTERRUPT_CALLBACK_EXTENSION_URI,
            ],
            "codex_extensions": [
                SESSION_QUERY_EXTENSION_URI,
                DISCOVERY_EXTENSION_URI,
                THREAD_LIFECYCLE_EXTENSION_URI,
                TURN_CONTROL_EXTENSION_URI,
                REVIEW_CONTROL_EXTENSION_URI,
                EXEC_CONTROL_EXTENSION_URI,
                COMPATIBILITY_PROFILE_EXTENSION_URI,
                WIRE_CONTRACT_EXTENSION_URI,
            ],
            "provider_private_metadata": list(_REQUEST_EXECUTION_PROVIDER_METADATA),
        },
        "extension_retention": extension_retention,
        "method_retention": method_retention,
        "consumer_guidance": [
            "Treat core A2A methods as the stable interoperability baseline for generic clients.",
            (
                "Treat this deployment as a single-tenant, shared-workspace coding profile; "
                "do not assume per-consumer workspace or tenant isolation."
            ),
            (
                "Treat urn:a2a:* extension URIs in this repository as shared extension "
                "conventions used across this repo family, not as claims that they are part "
                "of the A2A core baseline."
            ),
            (
                "Treat shared session-binding, stream-hints, and interrupt callback surfaces "
                "as shared extensions rather than provider-private Codex capabilities."
            ),
            (
                "Treat codex.* methods and codex.directory/codex.execution metadata as "
                "Codex-specific "
                "extensions or provider-private operational surfaces rather than portable "
                "A2A baseline capabilities."
            ),
            (
                "Use codex.discovery.* methods to discover stable skill.path and "
                "mention.path identifiers before constructing rich input items."
            ),
            (
                "Treat codex.threads.* as provider-private lifecycle management surfaces "
                "separate from codex.sessions.* query/control methods."
            ),
            (
                "Treat codex.turns.* as active-turn control surfaces rather than session "
                "query/history methods."
            ),
            (
                "Treat codex.review.* as reviewer control/watch surfaces. review/start "
                "starts a review turn and codex.review.watch exposes the declared "
                "task-stream bridge for coarse-grained lifecycle observation."
            ),
            (
                "codex.sessions.shell is deployment-conditional: discover it from the "
                "declared profile and current extension contracts before calling it, and "
                "treat it as a bounded shell snapshot helper for internal workflows."
            ),
            (
                "Treat codex.exec.* as the interactive standalone command runtime for "
                "internal or tightly controlled deployments. Use it for write/resize/"
                "terminate flows instead of inferring those semantics from "
                "codex.sessions.shell."
            ),
            (
                "Treat execution_environment fields as deployment-configured discovery "
                "metadata rather than per-turn snapshots of temporary approvals or "
                "runtime escalations."
            ),
            (
                "Treat this service's terminal tasks/resubscribe replay-once behavior as a "
                "declared service-level contract rather than a generic A2A baseline promise."
            ),
        ],
    }


def _build_method_contract_params(
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    unsupported: tuple[str, ...],
) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    if required:
        params["required"] = list(required)
    if optional:
        params["optional"] = list(optional)
    if unsupported:
        params["unsupported"] = list(unsupported)
    return params


def build_session_binding_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    return {
        "metadata_field": SHARED_SESSION_BINDING_FIELD,
        "behavior": "prefer_metadata_binding_else_create_session",
        "supported_metadata": [
            "shared.session.id",
            "codex.directory",
            "codex.execution",
        ],
        "provider_private_metadata": list(_REQUEST_EXECUTION_PROVIDER_METADATA),
        "request_execution_options": _build_request_execution_options_contract(),
        "profile": runtime_profile.summary_dict(),
        "notes": [
            (
                "If metadata.shared.session.id is provided, the server will send the "
                "message to that upstream session."
            ),
            (
                "Otherwise, the server will reuse any persisted binding when "
                "available or create a new upstream session."
            ),
            (
                "When no database state store is configured, the "
                "(identity, contextId)->session_id mapping remains an in-memory "
                "TTL cache."
            ),
        ],
    }


def build_streaming_extension_params() -> dict[str, Any]:
    artifact_stream_contract = build_artifact_stream_contract_params(
        field_path=SHARED_STREAM_METADATA_FIELD,
    )
    status_stream_contract = build_status_stream_contract_params(
        field_path=SHARED_STREAM_METADATA_FIELD,
    )
    interrupt_contract = build_interrupt_contract_params(
        field_path=SHARED_INTERRUPT_METADATA_FIELD,
    )
    session_contract = build_session_contract_params(
        field_path=SHARED_SESSION_METADATA_FIELD,
    )
    usage_contract = build_usage_contract_params(
        field_path=SHARED_USAGE_METADATA_FIELD,
    )
    return {
        "artifact_metadata_field": SHARED_STREAM_METADATA_FIELD,
        "status_metadata_field": SHARED_STREAM_METADATA_FIELD,
        "interrupt_metadata_field": SHARED_INTERRUPT_METADATA_FIELD,
        "session_metadata_field": SHARED_SESSION_METADATA_FIELD,
        "usage_metadata_field": SHARED_USAGE_METADATA_FIELD,
        "block_types": ["text", "reasoning", "tool_call"],
        "block_part_types": {
            "text": "TextPart",
            "reasoning": "TextPart",
            "tool_call": "DataPart",
        },
        "stream_fields": dict(artifact_stream_contract["field_paths"]),
        "status_stream_fields": dict(status_stream_contract["field_paths"]),
        "session_fields": dict(session_contract["field_paths"]),
        "interrupt_fields": dict(interrupt_contract["field_paths"]),
        "usage_fields": dict(usage_contract["field_paths"]),
        "artifact_stream_contract": artifact_stream_contract,
        "status_stream_contract": status_stream_contract,
        "session_contract": session_contract,
        "interrupt_contract": interrupt_contract,
        "usage_contract": usage_contract,
        "tool_call_payload_contract": build_tool_call_payload_contract_params(),
    }


def build_session_query_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    active_method_contracts = {
        key: contract
        for key, contract in SESSION_QUERY_METHOD_CONTRACTS.items()
        if key in snapshot.session_query_method_keys
    }
    active_query_methods = {
        key: contract.method for key, contract in active_method_contracts.items()
    }
    active_control_methods = {
        key: active_query_methods[key]
        for key in SESSION_CONTROL_METHOD_KEYS
        if key in active_query_methods
    }
    method_contracts: dict[str, Any] = {}
    pagination_applies_to: list[str] = []
    pagination_behavior_by_method: dict[str, str] = {}

    for method_contract in active_method_contracts.values():
        params_contract = _build_method_contract_params(
            required=method_contract.required_params,
            optional=method_contract.optional_params,
            unsupported=method_contract.unsupported_params,
        )
        result_contract: dict[str, Any] = {"fields": list(method_contract.result_fields)}
        if method_contract.items_type:
            result_contract["items_type"] = method_contract.items_type
        if method_contract.items_field:
            result_contract["items_field"] = method_contract.items_field

        contract_doc: dict[str, Any] = {
            "params": params_contract,
            "result": result_contract,
        }
        if method_contract.notification_response_status is not None:
            contract_doc["notification_response_status"] = (
                method_contract.notification_response_status
            )
        if method_contract.execution_binding is not None:
            contract_doc["execution_binding"] = method_contract.execution_binding
        if method_contract.session_binding is not None:
            contract_doc["session_binding"] = method_contract.session_binding
        if method_contract.uses_upstream_session_context is not None:
            contract_doc["uses_upstream_session_context"] = (
                method_contract.uses_upstream_session_context
            )
        if method_contract.notes:
            contract_doc["notes"] = list(method_contract.notes)
        method_contracts[method_contract.method] = contract_doc

        if method_contract.pagination_mode == SESSION_QUERY_PAGINATION_MODE:
            pagination_applies_to.append(method_contract.method)
            if method_contract.method == SESSION_QUERY_METHODS["list_sessions"]:
                pagination_behavior_by_method[method_contract.method] = "upstream_passthrough"
            elif method_contract.method == SESSION_QUERY_METHODS["get_session_messages"]:
                pagination_behavior_by_method[method_contract.method] = "local_tail_slice"

    return {
        "methods": active_query_methods,
        "control_methods": active_control_methods,
        "profile": runtime_profile.summary_dict(),
        "supported_metadata": list(_REQUEST_EXECUTION_PROVIDER_METADATA),
        "provider_private_metadata": list(_REQUEST_EXECUTION_PROVIDER_METADATA),
        "request_execution_options": _build_request_execution_options_contract(),
        "rich_input": {
            "prompt_async_part_types": ["text", "image", "mention", "skill"],
            "prompt_async_part_contracts": {
                "text": {"fields": ["type", "text"]},
                "image": {
                    "fields": ["type", "url"],
                    "optional_aliases": ["image_url", "imageUrl"],
                    "bytes_variant_fields": ["type", "bytes", "mimeType", "name"],
                    "maps_to": "turn/start.input[].type=input_image",
                },
                "mention": {
                    "fields": ["type", "name", "path"],
                    "path_examples": ["app://<connector-id>", "plugin://<name>@<marketplace>"],
                },
                "skill": {
                    "fields": ["type", "name", "path"],
                    "path_examples": ["/abs/path/to/SKILL.md"],
                },
            },
            "core_message_part_mapping": {
                "TextPart": "text",
                "FilePart(image only)": "input_image",
                "DataPart(type=mention|skill)": "mention|skill",
            },
            "notes": [
                (
                    "Core A2A message/send and message/stream keep the standard A2A part "
                    "surface and map only image FilePart plus mention/skill DataPart "
                    "payloads into Codex rich input items."
                ),
                (
                    "mention.path values are forwarded verbatim. The server does not infer "
                    "app or plugin identifiers from names."
                ),
                (
                    "local_image is not currently declared as part of the stable Codex A2A "
                    "rich input contract."
                ),
            ],
        },
        "pagination": {
            "mode": SESSION_QUERY_PAGINATION_MODE,
            "default_limit": SESSION_QUERY_DEFAULT_LIMIT,
            "max_limit": SESSION_QUERY_MAX_LIMIT,
            "behavior": SESSION_QUERY_PAGINATION_BEHAVIOR,
            "by_method": pagination_behavior_by_method,
            "params": list(SESSION_QUERY_PAGINATION_PARAMS),
            "applies_to": pagination_applies_to,
            "notes": [
                "codex.sessions.list forwards limit upstream to Codex thread/list",
                (
                    "codex.sessions.messages.list reads the full thread history first and "
                    "then keeps the most recent N mapped messages locally"
                ),
            ],
        },
        "method_contracts": method_contracts,
        "errors": {
            "business_codes": dict(SESSION_QUERY_ERROR_BUSINESS_CODES),
            "error_data_fields": list(SESSION_QUERY_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(SESSION_QUERY_INVALID_PARAMS_DATA_FIELDS),
        },
        "result_envelope": {},
        "context_semantics": {
            "a2a_context_id_field": "contextId",
            "upstream_session_id_field": SHARED_SESSION_BINDING_FIELD,
            "context_id_strategy": "equals_upstream_session_id",
            "notes": [
                (
                    "session query projections currently set contextId equal to the "
                    "upstream session_id"
                ),
                "metadata.shared.session.id carries the same upstream session identity explicitly",
            ],
        },
    }


def build_discovery_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    active_method_contracts = {
        key: contract
        for key, contract in DISCOVERY_METHOD_CONTRACTS.items()
        if contract.method in snapshot.discovery_methods
    }
    method_contracts: dict[str, Any] = {}

    for contract in active_method_contracts.values():
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=(),
            ),
            "result": {"fields": list(contract.result_fields)},
        }
        if contract.items_type:
            method_contract_doc["result"]["items_type"] = contract.items_type
        if contract.items_field:
            method_contract_doc["result"]["items_field"] = contract.items_field
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        if contract.notes:
            method_contract_doc["notes"] = list(contract.notes)
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": dict(DISCOVERY_METHODS),
        "profile": runtime_profile.summary_dict(),
        "method_contracts": method_contracts,
        "stable_item_fields": {
            "skill": [
                "name",
                "path",
                "description",
                "enabled",
                "scope",
                "interface",
                "codex.raw",
            ],
            "app": [
                "id",
                "name",
                "description",
                "is_accessible",
                "is_enabled",
                "install_url",
                "mention_path",
                "codex.raw",
            ],
            "plugin_marketplace": [
                "marketplace_name",
                "marketplace_path",
                "interface",
                "plugins",
                "codex.raw",
            ],
            "plugin_summary": [
                "name",
                "description",
                "enabled",
                "mention_path",
                "interface",
                "codex.raw",
            ],
            "plugin_detail": [
                "name",
                "marketplace_name",
                "marketplace_path",
                "mention_path",
                "summary",
                "skills",
                "apps",
                "mcp_servers",
                "codex.raw",
            ],
        },
        "notification_bridge": {
            "upstream_notifications": ["skills/changed", "app/list/updated"],
            "current_delivery": "codex.discovery.watch task stream",
            "notes": [
                (
                    "This service does not expose a standalone server-push JSON-RPC transport. "
                    "Use codex.discovery.watch plus tasks/resubscribe to receive invalidation "
                    "and refresh signals."
                )
            ],
        },
        "task_streaming": {
            "task_stream_method": TASKS_RESUBSCRIBE_METHOD,
            "http_subscribe_endpoint": TASKS_SUBSCRIBE_HTTP_ENDPOINT,
            "watch_method": DISCOVERY_METHODS["watch"],
            "supported_events": ["skills.changed", "apps.updated"],
            "data_part_payloads": {
                "skills.changed": {"kind": "skills_changed", "source": "skills/changed"},
                "apps.updated": {
                    "kind": "apps_updated",
                    "source": "app/list/updated",
                    "items_field": "items",
                },
            },
        },
        "consumer_guidance": [
            "Use codex.discovery.skills.list to obtain stable skill.path values.",
            (
                "Use codex.discovery.apps.list or codex.discovery.plugins.list to obtain "
                "stable mention_path values."
            ),
            (
                "Prefer stable normalized fields for portability; inspect codex.raw only for "
                "provider-specific details not covered by the declared contract."
            ),
        ],
        "errors": {
            "business_codes": dict(DISCOVERY_ERROR_BUSINESS_CODES),
            "error_data_fields": list(DISCOVERY_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(DISCOVERY_INVALID_PARAMS_DATA_FIELDS),
        },
    }


def build_thread_lifecycle_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    snapshot = build_capability_snapshot(runtime_profile=runtime_profile)
    active_method_contracts = {
        key: contract
        for key, contract in THREAD_LIFECYCLE_METHOD_CONTRACTS.items()
        if contract.method in snapshot.thread_lifecycle_methods
    }
    method_contracts: dict[str, Any] = {}

    for contract in active_method_contracts.values():
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=(),
            ),
            "result": {"fields": list(contract.result_fields)},
        }
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        if contract.notes:
            method_contract_doc["notes"] = list(contract.notes)
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": dict(THREAD_LIFECYCLE_METHODS),
        "method_contracts": method_contracts,
        "profile": runtime_profile.summary_dict(),
        "supported_metadata": ["codex.directory"],
        "provider_private_metadata": ["codex.directory"],
        "stable_thread_fields": ["id", "title", "status", "codex.raw"],
        "notification_bridge": {
            "upstream_notifications": [
                "thread/started",
                "thread/status/changed",
                "thread/archived",
                "thread/unarchived",
                "thread/closed",
            ],
            "current_delivery": "codex.threads.watch task stream",
            "notes": [
                (
                    "This service does not expose standalone server-push JSON-RPC "
                    "notifications. Use codex.threads.watch plus tasks/resubscribe to "
                    "consume lifecycle events."
                ),
                (
                    "thread/unsubscribe is intentionally excluded from this first-stage "
                    "stable surface because upstream unsubscribe is connection-scoped while "
                    "this service currently shares one underlying Codex client connection."
                ),
                (
                    "Use codex.threads.watch.release or tasks/cancel to release a watch that "
                    "was created by the current owner."
                ),
            ],
        },
        "task_streaming": {
            "task_stream_method": TASKS_RESUBSCRIBE_METHOD,
            "http_subscribe_endpoint": TASKS_SUBSCRIBE_HTTP_ENDPOINT,
            "watch_method": THREAD_LIFECYCLE_METHODS["watch"],
            "supported_events": list(THREAD_LIFECYCLE_SUPPORTED_EVENTS),
            "data_part_payloads": {
                "thread.started": {
                    "kind": "thread_started",
                    "source": "thread/started",
                    "thread_field": "thread",
                },
                "thread.status.changed": {
                    "kind": "thread_status_changed",
                    "source": "thread/status/changed",
                    "status_field": "status",
                },
                "thread.archived": {
                    "kind": "thread_archived",
                    "source": "thread/archived",
                },
                "thread.unarchived": {
                    "kind": "thread_unarchived",
                    "source": "thread/unarchived",
                    "thread_field": "thread",
                },
                "thread.closed": {
                    "kind": "thread_closed",
                    "source": "thread/closed",
                },
            },
        },
        "consumer_guidance": [
            (
                "Treat codex.threads.* as provider-private lifecycle management methods "
                "separate from codex.sessions.* query/control surfaces."
            ),
            (
                "Prefer codex.threads.watch when clients need status transitions or archive/"
                "restore invalidation signals."
            ),
        ],
        "errors": {
            "business_codes": dict(THREAD_LIFECYCLE_ERROR_BUSINESS_CODES),
            "error_data_fields": list(THREAD_LIFECYCLE_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(THREAD_LIFECYCLE_INVALID_PARAMS_DATA_FIELDS),
        },
    }


def build_turn_control_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    active_methods = dict(TURN_CONTROL_METHODS) if runtime_profile.turn_control_enabled else {}
    method_contracts: dict[str, Any] = {}
    for key, contract in TURN_CONTROL_METHOD_CONTRACTS.items():
        if key not in active_methods:
            continue
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=contract.unsupported_params,
            ),
            "result": {"fields": list(contract.result_fields)},
        }
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        if contract.notes:
            method_contract_doc["notes"] = list(contract.notes)
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": active_methods,
        "method_contracts": method_contracts,
        "profile": runtime_profile.summary_dict(),
        "availability": runtime_profile.turn_control.availability,
        "toggle": runtime_profile.turn_control.toggle,
        "supported_metadata": [],
        "provider_private_metadata": [],
        "consumer_guidance": [
            (
                "Use codex.turns.steer only when the target thread already has an active "
                "regular turn that is still in progress."
            ),
            (
                "Do not treat codex.turns.steer as an alias for turn/start. It appends "
                "input to an existing active turn and intentionally rejects turn-level "
                "override fields."
            ),
        ],
        "errors": {
            "business_codes": dict(TURN_CONTROL_ERROR_BUSINESS_CODES),
            "error_data_fields": list(TURN_CONTROL_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(TURN_CONTROL_INVALID_PARAMS_DATA_FIELDS),
        },
    }


def build_review_control_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    active_methods = dict(REVIEW_CONTROL_METHODS) if runtime_profile.review_control_enabled else {}
    method_contracts: dict[str, Any] = {}
    for key, contract in REVIEW_CONTROL_METHOD_CONTRACTS.items():
        if key not in active_methods:
            continue
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=contract.unsupported_params,
            ),
            "result": {"fields": list(contract.result_fields)},
        }
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        if contract.notes:
            method_contract_doc["notes"] = list(contract.notes)
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": active_methods,
        "method_contracts": method_contracts,
        "profile": runtime_profile.summary_dict(),
        "availability": runtime_profile.review_control.availability,
        "toggle": runtime_profile.review_control.toggle,
        "supported_metadata": [],
        "provider_private_metadata": [],
        "target_contracts": {
            "uncommittedChanges": {"required_fields": ["type"]},
            "baseBranch": {"required_fields": ["type", "branch"]},
            "commit": {"required_fields": ["type", "sha"], "optional_fields": ["title"]},
            "custom": {"required_fields": ["type", "instructions"]},
        },
        "delivery_values": ["inline", "detached"],
        "notification_bridge": {
            "upstream_notifications": [
                "thread/status/changed",
                "turn/completed",
            ],
            "current_delivery": "codex.review.watch task stream",
            "notes": [
                (
                    "This service does not expose standalone server-push JSON-RPC "
                    "review notifications. Use codex.review.watch plus tasks/resubscribe "
                    "to consume review lifecycle events."
                ),
                (
                    "review.started is emitted from the supplied watch handle; "
                    "review.status.changed is best-effort and review.completed / "
                    "review.failed are derived from turn/completed."
                ),
            ],
        },
        "task_streaming": {
            "task_stream_method": TASKS_RESUBSCRIBE_METHOD,
            "http_subscribe_endpoint": TASKS_SUBSCRIBE_HTTP_ENDPOINT,
            "watch_method": REVIEW_CONTROL_METHODS["watch"],
            "supported_events": list(REVIEW_CONTROL_SUPPORTED_EVENTS),
            "data_part_payloads": {
                "review.started": {
                    "kind": "review_started",
                    "source": "review/start",
                    "required_fields": ["thread_id", "review_thread_id", "turn_id"],
                },
                "review.status.changed": {
                    "kind": "review_status_changed",
                    "source": "thread/status/changed",
                    "status_field": "status",
                },
                "review.completed": {
                    "kind": "review_completed",
                    "source": "turn/completed",
                    "review_field": "review",
                    "status_field": "status",
                },
                "review.failed": {
                    "kind": "review_failed",
                    "source": "turn/completed",
                    "review_field": "review",
                    "status_field": "status",
                },
            },
        },
        "consumer_guidance": [
            (
                "Use review/start when you want the upstream reviewer surface, not when you "
                "simply want to send a slash command through codex.sessions.command."
            ),
            (
                "Use codex.review.watch when clients need a stable task-stream bridge "
                "for coarse-grained review lifecycle observation."
            ),
        ],
        "errors": {
            "business_codes": dict(REVIEW_CONTROL_ERROR_BUSINESS_CODES),
            "error_data_fields": list(REVIEW_CONTROL_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(REVIEW_CONTROL_INVALID_PARAMS_DATA_FIELDS),
        },
    }


def build_exec_control_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    active_methods = dict(EXEC_CONTROL_METHODS) if runtime_profile.exec_control_enabled else {}
    method_contracts: dict[str, Any] = {}
    for key, contract in EXEC_CONTROL_METHOD_CONTRACTS.items():
        if key not in active_methods:
            continue
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=(),
            ),
            "result": {"fields": list(contract.result_fields)},
        }
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        if contract.execution_binding is not None:
            method_contract_doc["execution_binding"] = contract.execution_binding
        if contract.notes:
            method_contract_doc["notes"] = list(contract.notes)
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": active_methods,
        "method_contracts": method_contracts,
        "profile": runtime_profile.summary_dict(),
        "availability": runtime_profile.exec_control.availability,
        "toggle": runtime_profile.exec_control.toggle,
        "supported_metadata": ["codex.directory"],
        "provider_private_metadata": ["codex.directory"],
        "task_streaming": {
            "start_result_fields": ["ok", "task_id", "context_id", "process_id"],
            "task_status_source": "tasks/get",
            "task_stream_method": TASKS_RESUBSCRIBE_METHOD,
            "terminal_delivery": "result_artifact_plus_terminal_status",
            "notes": [
                (
                    "codex.exec.start returns an immediate handle while stdout/stderr deltas "
                    "flow through the standard A2A task stream."
                ),
                (
                    "Interactive exec sessions are standalone runtimes keyed by process_id; "
                    "they are not upstream thread-bound shells."
                ),
            ],
        },
        "errors": {
            "business_codes": dict(EXEC_CONTROL_ERROR_BUSINESS_CODES),
            "error_data_fields": list(EXEC_CONTROL_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(EXEC_CONTROL_INVALID_PARAMS_DATA_FIELDS),
        },
    }


def build_interrupt_callback_extension_params(
    *,
    runtime_profile: RuntimeProfile,
) -> dict[str, Any]:
    method_contracts: dict[str, Any] = {}
    for contract in INTERRUPT_CALLBACK_METHOD_CONTRACTS.values():
        method_contract_doc: dict[str, Any] = {
            "params": _build_method_contract_params(
                required=contract.required_params,
                optional=contract.optional_params,
                unsupported=(),
            ),
            "result": {"fields": list(INTERRUPT_SUCCESS_RESULT_FIELDS)},
        }
        if contract.notification_response_status is not None:
            method_contract_doc["notification_response_status"] = (
                contract.notification_response_status
            )
        method_contracts[contract.method] = method_contract_doc

    return {
        "methods": dict(INTERRUPT_CALLBACK_METHODS),
        "method_contracts": method_contracts,
        "supported_interrupt_events": [
            "permission.asked",
            "question.asked",
            "permissions.asked",
            "elicitation.asked",
        ],
        "permission_reply_values": ["once", "always", "reject"],
        "question_reply_contract": {
            "answers": "array of answer arrays (same order as asked questions)"
        },
        "permissions_reply_contract": {
            "permissions": "granted subset object matching the requested permission profile",
            "scope": "optional persistence scope: turn or session",
        },
        "elicitation_reply_contract": {
            "action": "accept, decline, or cancel",
            "content": (
                "structured response payload for accepted elicitations; null for decline/cancel"
            ),
        },
        "request_id_field": f"{SHARED_INTERRUPT_METADATA_FIELD}.request_id",
        "supported_metadata": ["codex.directory"],
        "provider_private_metadata": ["codex.directory"],
        "context_fields": {
            "directory": CODEX_DIRECTORY_METADATA_FIELD,
        },
        "success_result_fields": list(INTERRUPT_SUCCESS_RESULT_FIELDS),
        "errors": {
            "business_codes": dict(INTERRUPT_ERROR_BUSINESS_CODES),
            "error_types": list(INTERRUPT_ERROR_TYPES),
            "error_data_fields": list(INTERRUPT_ERROR_DATA_FIELDS),
            "invalid_params_data_fields": list(INTERRUPT_INVALID_PARAMS_DATA_FIELDS),
        },
        "profile": runtime_profile.summary_dict(),
    }
