from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2a.server.apps.jsonrpc.jsonrpc_app import JSONRPCApplication

from codex_a2a.execution.request_overrides import request_execution_options_fields
from codex_a2a.profile.runtime import RuntimeProfile

COMPATIBILITY_PROFILE_EXTENSION_URI = "urn:codex-a2a:compatibility-profile/v1"
WIRE_CONTRACT_EXTENSION_URI = "urn:codex-a2a:wire-contract/v1"
SESSION_BINDING_EXTENSION_URI = "urn:a2a:session-binding/v1"
STREAMING_EXTENSION_URI = "urn:a2a:stream-hints/v1"
SESSION_QUERY_EXTENSION_URI = "urn:codex-a2a:codex-session-query/v1"
DISCOVERY_EXTENSION_URI = "urn:codex-a2a:codex-discovery/v1"
THREAD_LIFECYCLE_EXTENSION_URI = "urn:codex-a2a:codex-thread-lifecycle/v1"
INTERRUPT_RECOVERY_EXTENSION_URI = "urn:codex-a2a:codex-interrupt-recovery/v1"
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
class InterruptRecoveryMethodContract:
    method: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    result_fields: tuple[str, ...] = ()
    items_type: str | None = None
    items_field: str | None = None
    notification_response_status: int | None = None
    notes: tuple[str, ...] = ()


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
    "credential_id",
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

INTERRUPT_RECOVERY_METHOD_CONTRACTS: dict[str, InterruptRecoveryMethodContract] = {
    "list": InterruptRecoveryMethodContract(
        method="codex.interrupts.list",
        optional_params=("type",),
        result_fields=("items",),
        items_type="InterruptRecoveryItem[]",
        items_field="items",
        notification_response_status=204,
        notes=(
            (
                "This method lists adapter-local active interrupt requests that are still "
                "pending for the current authenticated caller."
            ),
            (
                "Results are filtered to the current authenticated identity and credential "
                "binding when that information is available."
            ),
            (
                "Use interrupt recovery only to rediscover pending request_ids. Resolve the "
                "interrupt itself through a2a.interrupt.* callback methods."
            ),
        ),
    ),
}
INTERRUPT_RECOVERY_METHODS: dict[str, str] = {
    key: contract.method for key, contract in INTERRUPT_RECOVERY_METHOD_CONTRACTS.items()
}
INTERRUPT_RECOVERY_RESULT_ITEM_FIELDS: tuple[str, ...] = (
    "request_id",
    "interrupt_type",
    "session_id",
    "task_id",
    "context_id",
    "created_at",
    "expires_at",
    "properties",
)
INTERRUPT_RECOVERY_INTERRUPT_TYPES: tuple[str, ...] = (
    "permission",
    "question",
    "permissions",
    "elicitation",
)
INTERRUPT_RECOVERY_INVALID_PARAMS_DATA_FIELDS: tuple[str, ...] = (
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
    "AUTHORIZATION_FORBIDDEN": -32007,
    "TURN_NOT_STEERABLE": -32012,
    "TURN_FORBIDDEN": -32013,
}
TURN_CONTROL_ERROR_DATA_FIELDS: tuple[str, ...] = (
    "type",
    "method",
    "capability",
    "credential_id",
    "required_principal",
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
    "credential_id",
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
    interrupt_recovery_methods: tuple[str, ...]
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
    interrupt_recovery_methods = tuple(INTERRUPT_RECOVERY_METHODS.values())
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
        *interrupt_recovery_methods,
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
        interrupt_recovery_methods=interrupt_recovery_methods,
        turn_control_methods=turn_control_methods,
        review_control_methods=review_control_methods,
        exec_control_methods=exec_control_methods,
        conditional_methods=conditional_methods,
    )


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
