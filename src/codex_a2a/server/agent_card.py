from __future__ import annotations

from typing import Any

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityScheme,
    TransportProtocol,
)

from codex_a2a.config import Settings
from codex_a2a.contracts.extensions import (
    COMPATIBILITY_PROFILE_EXTENSION_URI,
    DISCOVERY_EXTENSION_URI,
    EXEC_CONTROL_EXTENSION_URI,
    INTERRUPT_CALLBACK_EXTENSION_URI,
    REVIEW_CONTROL_EXTENSION_URI,
    SESSION_BINDING_EXTENSION_URI,
    SESSION_QUERY_EXTENSION_URI,
    STREAMING_EXTENSION_URI,
    THREAD_LIFECYCLE_EXTENSION_URI,
    TURN_CONTROL_EXTENSION_URI,
    WIRE_CONTRACT_EXTENSION_URI,
    build_compatibility_profile_params,
    build_discovery_extension_params,
    build_exec_control_extension_params,
    build_interrupt_callback_extension_params,
    build_review_control_extension_params,
    build_session_binding_extension_params,
    build_session_query_extension_params,
    build_streaming_extension_params,
    build_thread_lifecycle_extension_params,
    build_turn_control_extension_params,
    build_wire_contract_extension_params,
)
from codex_a2a.media_modes import (
    DEFAULT_INPUT_MEDIA_MODES,
    DEFAULT_OUTPUT_MEDIA_MODES,
    JSON_OUTPUT_MEDIA_MODES,
    JSON_RPC_INPUT_MEDIA_MODES,
    TEXT_OUTPUT_MEDIA_MODES,
)
from codex_a2a.profile.runtime import RuntimeProfile, build_runtime_profile


def _select_public_extension_params(
    params: dict[str, Any],
    *,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    return {key: params[key] for key in keys if key in params}


def _build_public_streaming_extension_params(
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_metadata_field": params["artifact_metadata_field"],
        "status_metadata_field": params["status_metadata_field"],
        "interrupt_metadata_field": params["interrupt_metadata_field"],
        "session_metadata_field": params["session_metadata_field"],
        "usage_metadata_field": params["usage_metadata_field"],
        "block_types": params["block_types"],
        "block_part_types": params["block_part_types"],
        "stream_fields": _select_public_extension_params(
            params["stream_fields"],
            keys=("block_type", "message_id", "sequence", "source"),
        ),
        "status_stream_fields": _select_public_extension_params(
            params["status_stream_fields"],
            keys=("type", "status", "source", "event_id"),
        ),
        "session_fields": _select_public_extension_params(
            params["session_fields"],
            keys=("id", "title"),
        ),
        "interrupt_fields": _select_public_extension_params(
            params["interrupt_fields"],
            keys=("request_id", "type", "phase", "resolution"),
        ),
        "usage_fields": _select_public_extension_params(
            params["usage_fields"],
            keys=("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"),
        ),
    }


def _build_agent_card_description(
    settings: Settings,
    runtime_profile: RuntimeProfile,
    *,
    include_detailed_contracts: bool,
) -> str:
    base = (settings.a2a_description or "").strip() or "Codex A2A runtime adapter."
    if not include_detailed_contracts:
        public_parts: list[str] = [
            base,
            (
                "Supports HTTP+JSON and JSON-RPC transports, standard A2A messaging, "
                "and authenticated extended Agent Card discovery."
            ),
            (
                "Single-tenant deployment; all consumers share the same underlying Codex "
                "workspace/environment."
            ),
        ]
        project = runtime_profile.runtime_context.project
        if isinstance(project, str) and project.strip():
            public_parts.append(f"Deployment project: {project}.")
        return " ".join(public_parts)

    summary = (
        "Supports HTTP+JSON and JSON-RPC transports, standard A2A messaging "
        "(message/send, message/stream), authenticated extended Agent Card "
        "(agent/getAuthenticatedExtendedCard), task APIs (tasks/get, tasks/cancel, "
        "tasks/resubscribe), shared session-binding and streaming contracts, "
        "Codex session-query, thread lifecycle, active-turn control, review control, "
        "discovery, and interactive exec extensions, shared interrupt callback "
        "extensions, a machine-readable "
        "compatibility profile, and a machine-readable wire contract."
    )
    parts: list[str] = [base, summary]
    parts.append(
        "Within one codex-a2a instance, all consumers share the same "
        "underlying Codex workspace/environment."
    )
    parts.append(
        "Terminal tasks/resubscribe replay-once behavior is declared as a "
        "service-level contract for this deployment."
    )
    parts.append("This server profile is intended for single-tenant, self-hosted coding workflows.")
    runtime_context = runtime_profile.runtime_context
    project = runtime_context.project
    if isinstance(project, str) and project.strip():
        parts.append(f"Deployment project: {project}.")
    workspace_root = runtime_context.workspace_root
    if isinstance(workspace_root, str) and workspace_root.strip():
        parts.append(f"Workspace root: {workspace_root}.")
    provider_id = runtime_context.provider_id
    model_id = runtime_context.model_id
    if isinstance(provider_id, str) and isinstance(model_id, str):
        parts.append(f"Default upstream model: {provider_id}/{model_id}.")
    return " ".join(parts)


def _build_chat_examples(project: str | None) -> list[str]:
    examples = [
        "Explain what this repository does.",
        "Summarize the API endpoints in this project.",
    ]
    if project:
        examples.append(f"Summarize current work items for project {project}.")
    return examples


def _build_agent_extensions(
    *,
    settings: Settings,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentExtension]:
    session_binding_extension_params = build_session_binding_extension_params(
        runtime_profile=runtime_profile,
    )
    streaming_extension_params = build_streaming_extension_params()
    session_query_extension_params = build_session_query_extension_params(
        runtime_profile=runtime_profile,
    )
    discovery_extension_params = build_discovery_extension_params(
        runtime_profile=runtime_profile,
    )
    thread_lifecycle_extension_params = build_thread_lifecycle_extension_params(
        runtime_profile=runtime_profile,
    )
    turn_control_extension_params = build_turn_control_extension_params(
        runtime_profile=runtime_profile,
    )
    review_control_extension_params = build_review_control_extension_params(
        runtime_profile=runtime_profile,
    )
    exec_control_extension_params = build_exec_control_extension_params(
        runtime_profile=runtime_profile,
    )
    interrupt_callback_extension_params = build_interrupt_callback_extension_params(
        runtime_profile=runtime_profile,
    )
    wire_contract_extension_params = build_wire_contract_extension_params(
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )
    compatibility_profile_params = build_compatibility_profile_params(
        protocol_version=settings.a2a_protocol_version,
        runtime_profile=runtime_profile,
    )

    return [
        AgentExtension(
            uri=SESSION_BINDING_EXTENSION_URI,
            required=False,
            description=(
                "Shared contract to bind A2A messages to an existing Codex session "
                "when continuing a previous chat. Clients should pass "
                "metadata.shared.session.id. The metadata.codex.directory and "
                "metadata.codex.execution fields remain available as Codex-private "
                "request overrides under server-side validation."
            ),
            params=(
                session_binding_extension_params
                if include_detailed_contracts
                else _select_public_extension_params(
                    session_binding_extension_params,
                    keys=(
                        "metadata_field",
                        "behavior",
                        "supported_metadata",
                        "provider_private_metadata",
                    ),
                )
            ),
        ),
        AgentExtension(
            uri=STREAMING_EXTENSION_URI,
            required=False,
            description=(
                "Shared streaming metadata contract for canonical block hints, "
                "timeline identity, usage, and interactive interrupt metadata."
            ),
            params=(
                streaming_extension_params
                if include_detailed_contracts
                else _build_public_streaming_extension_params(streaming_extension_params)
            ),
        ),
        AgentExtension(
            uri=SESSION_QUERY_EXTENSION_URI,
            required=False,
            description=(
                "Support Codex session list/history queries via custom JSON-RPC methods "
                "on the agent's A2A JSON-RPC interface, including structured rich "
                "input for codex.sessions.prompt_async."
            ),
            params=session_query_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=DISCOVERY_EXTENSION_URI,
            required=False,
            description=(
                "Expose read-only skills/apps/plugins discovery plus a task-stream "
                "notification bridge for invalidation and refresh signals."
            ),
            params=discovery_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=THREAD_LIFECYCLE_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private thread lifecycle control plus a task-stream "
                "notification bridge for lifecycle status, archive, and restore "
                "signals."
            ),
            params=thread_lifecycle_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=TURN_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private active-turn steering through the custom "
                "JSON-RPC method codex.turns.steer."
            ),
            params=turn_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=REVIEW_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose provider-private reviewer control plus a task-stream "
                "watch bridge through the custom JSON-RPC methods "
                "codex.review.start and codex.review.watch."
            ),
            params=review_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=EXEC_CONTROL_EXTENSION_URI,
            required=False,
            description=(
                "Expose standalone interactive command execution via custom JSON-RPC "
                "methods codex.exec.start, codex.exec.write, codex.exec.resize, and "
                "codex.exec.terminate."
            ),
            params=exec_control_extension_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=INTERRUPT_CALLBACK_EXTENSION_URI,
            required=False,
            description=(
                "Handle interactive interrupt callbacks generated during "
                "streaming through shared JSON-RPC methods."
            ),
            params=(
                interrupt_callback_extension_params
                if include_detailed_contracts
                else _select_public_extension_params(
                    interrupt_callback_extension_params,
                    keys=("methods", "supported_interrupt_events", "request_id_field"),
                )
            ),
        ),
        AgentExtension(
            uri=COMPATIBILITY_PROFILE_EXTENSION_URI,
            required=False,
            description=(
                "Machine-readable compatibility profile for the current A2A core "
                "baseline, declared custom extensions, and retention policy."
            ),
            params=compatibility_profile_params if include_detailed_contracts else None,
        ),
        AgentExtension(
            uri=WIRE_CONTRACT_EXTENSION_URI,
            required=False,
            description=(
                "Declare the current JSON-RPC/HTTP method boundary and the "
                "unsupported method error contract for generic A2A clients."
            ),
            params=wire_contract_extension_params if include_detailed_contracts else None,
        ),
    ]


def _build_agent_skills(
    *,
    settings: Settings,
    include_detailed_contracts: bool,
) -> list[AgentSkill]:
    if not include_detailed_contracts:
        return [
            AgentSkill(
                id="codex.chat",
                name="Codex Chat",
                description=(
                    "Handle core A2A chat turns with shared session binding and "
                    "Codex-backed streaming."
                ),
                tags=["assistant", "coding", "codex", "core-a2a"],
                input_modes=list(DEFAULT_INPUT_MEDIA_MODES),
                output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.sessions.query",
                name="Codex Sessions Query",
                description=(
                    "Inspect Codex sessions and history through provider-private "
                    "JSON-RPC extensions."
                ),
                tags=["codex", "sessions", "history", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.sessions.control",
                name="Codex Sessions Control",
                description=(
                    "Start async Codex session turns and issue provider-private "
                    "session command or shell control methods."
                ),
                tags=["codex", "sessions", "control", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.discovery.query",
                name="Codex Discovery Query",
                description=(
                    "List skills, apps, and plugins through provider-private "
                    "JSON-RPC discovery methods."
                ),
                tags=["codex", "discovery", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.discovery.watch",
                name="Codex Discovery Watch",
                description=(
                    "Start provider-private discovery watch tasks that emit "
                    "structured invalidation events through A2A task streams."
                ),
                tags=["codex", "discovery", "watch", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.threads.control",
                name="Codex Thread Control",
                description=(
                    "Manage provider-private thread fork, archive, unarchive, "
                    "metadata-update, and watch-release actions."
                ),
                tags=["codex", "threads", "control", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.threads.watch",
                name="Codex Thread Watch",
                description=(
                    "Start and release provider-private thread lifecycle watch "
                    "tasks that emit structured events through A2A task streams."
                ),
                tags=["codex", "threads", "watch", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.turns.control",
                name="Codex Turn Control",
                description=(
                    "Append additional input to an active regular turn through the "
                    "provider-private codex.turns.steer method."
                ),
                tags=["codex", "turns", "control", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.review.control",
                name="Codex Review Control",
                description=(
                    "Start provider-private review turns against uncommitted changes, "
                    "base branches, commits, or custom instructions."
                ),
                tags=["codex", "review", "control", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.review.watch",
                name="Codex Review Watch",
                description=(
                    "Start provider-private review watch tasks that emit "
                    "coarse-grained lifecycle events through A2A task streams."
                ),
                tags=["codex", "review", "watch", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.interrupt.callback",
                name="Codex Interrupt Callback",
                description=("Reply to shared interrupt callbacks emitted during streaming."),
                tags=["interrupt", "shared"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.exec.control",
                name="Codex Exec Control",
                description=(
                    "Start and control standalone interactive command execution "
                    "through provider-private JSON-RPC extensions."
                ),
                tags=["codex", "exec", "control", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(JSON_OUTPUT_MEDIA_MODES),
            ),
            AgentSkill(
                id="codex.exec.stream",
                name="Codex Exec Stream",
                description=(
                    "Consume interactive exec stdout/stderr and terminal summaries "
                    "through A2A task streams after codex.exec.start."
                ),
                tags=["codex", "exec", "stream", "provider-private"],
                input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                output_modes=list(TEXT_OUTPUT_MEDIA_MODES),
            ),
        ]

    skills = [
        AgentSkill(
            id="codex.chat",
            name="Codex Chat",
            description=(
                "Handle message/send and message/stream requests by routing user text, "
                "image FilePart inputs, and codex rich-input DataPart payloads to "
                "Codex sessions."
            ),
            tags=["assistant", "coding", "codex"],
            examples=_build_chat_examples(settings.a2a_project),
            input_modes=list(DEFAULT_INPUT_MEDIA_MODES),
            output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.sessions.query",
            name="Codex Sessions Query",
            description=(
                "Query Codex sessions and message histories via JSON-RPC extension "
                "methods codex.sessions.list and codex.sessions.messages.list."
            ),
            tags=["codex", "sessions", "history"],
            examples=[
                "List Codex sessions (method codex.sessions.list).",
                "List messages for a session (method codex.sessions.messages.list).",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.sessions.control",
            name="Codex Sessions Control",
            description=(
                "Start async session turns and issue session-scoped command or "
                "one-shot shell control methods via provider-private JSON-RPC."
            ),
            tags=["codex", "sessions", "control", "commands"],
            examples=[
                "Start an async session turn (method codex.sessions.prompt_async).",
                "Run a one-shot shell snapshot for a session (method codex.sessions.shell).",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.discovery.query",
            name="Codex Discovery Query",
            description=(
                "List skills, apps, plugins, and stable path identifiers via "
                "codex.discovery.* query methods."
            ),
            tags=["codex", "discovery", "skills", "apps", "plugins"],
            examples=[
                "List available Codex skills (method codex.discovery.skills.list).",
                "List available apps or plugins before constructing mention.path values.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.discovery.watch",
            name="Codex Discovery Watch",
            description=(
                "Start discovery watch tasks via codex.discovery.watch and consume "
                "structured invalidation events through A2A task streams."
            ),
            tags=["codex", "discovery", "watch", "tasks"],
            examples=[
                "Start a discovery watch stream (method codex.discovery.watch).",
                "Resume a discovery watch task with tasks/resubscribe.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.threads.control",
            name="Codex Thread Control",
            description=(
                "Manage thread fork/archive/unarchive/metadata-update/watch-release flows via "
                "codex.threads.* control methods."
            ),
            tags=["codex", "threads", "control", "lifecycle"],
            examples=[
                "Fork a Codex thread (method codex.threads.fork).",
                "Update persisted git_info for a thread (method codex.threads.metadata.update).",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.threads.watch",
            name="Codex Thread Watch",
            description=(
                "Start and release thread lifecycle watch tasks via codex.threads.watch "
                "and codex.threads.watch.release, then consume structured lifecycle "
                "events through A2A task streams."
            ),
            tags=["codex", "threads", "watch", "lifecycle"],
            examples=[
                "Start a lifecycle watch stream (method codex.threads.watch).",
                "Release a lifecycle watch stream (method codex.threads.watch.release).",
                "Resume a lifecycle watch task with tasks/resubscribe.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.turns.control",
            name="Codex Turn Control",
            description=(
                "Append additional user input to an active regular turn via codex.turns.steer."
            ),
            tags=["codex", "turns", "control", "active-turn"],
            examples=[
                "Append follow-up guidance to the active turn (method codex.turns.steer).",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.review.control",
            name="Codex Review Control",
            description=(
                "Start review turns via codex.review.start for uncommitted changes, "
                "base branches, commits, or custom reviewer instructions."
            ),
            tags=["codex", "review", "control"],
            examples=[
                "Start an inline commit review (method codex.review.start).",
                "Start a detached review for current uncommitted changes.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.review.watch",
            name="Codex Review Watch",
            description=(
                "Start review watch tasks via codex.review.watch and consume "
                "coarse-grained review lifecycle events through A2A task streams."
            ),
            tags=["codex", "review", "watch"],
            examples=[
                "Start a review watch stream after codex.review.start.",
                "Resume a review watch task with tasks/resubscribe.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.interrupt.callback",
            name="Codex Interrupt Callback",
            description=(
                "Reply permission/question/permissions/elicitation interrupts emitted "
                "during streaming via shared JSON-RPC interrupt callback methods."
            ),
            tags=[
                "codex",
                "interrupt",
                "permission",
                "question",
                "permissions",
                "elicitation",
                "shared",
            ],
            examples=[
                "Reply once/always/reject to a permission request by request_id.",
                "Submit answers for a question request by request_id.",
                "Grant a permissions subset or answer an elicitation request by request_id.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.exec.control",
            name="Codex Exec Control",
            description=(
                "Start and control standalone interactive command execution via "
                "codex.exec.start/write/resize/terminate."
            ),
            tags=["codex", "exec", "terminal", "control"],
            examples=[
                "Start an interactive exec session (method codex.exec.start).",
                "Write stdin bytes or resize the exec PTY by process_id.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.exec.stream",
            name="Codex Exec Stream",
            description=(
                "Consume interactive exec stdout/stderr deltas and terminal result "
                "summaries through A2A task streams after codex.exec.start."
            ),
            tags=["codex", "exec", "terminal", "stream"],
            examples=[
                "Resume an exec task stream with tasks/resubscribe after codex.exec.start.",
                "Read final exec result text from the completed task artifact or status message.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(TEXT_OUTPUT_MEDIA_MODES),
        ),
    ]
    return skills


def _build_agent_card(
    settings: Settings,
    *,
    runtime_profile: RuntimeProfile | None,
    include_detailed_contracts: bool,
) -> AgentCard:
    public_url = settings.a2a_public_url.rstrip("/")
    runtime_profile = runtime_profile or build_runtime_profile(settings)
    security_schemes: dict[str, SecurityScheme] = {
        "bearerAuth": SecurityScheme(
            root=HTTPAuthSecurityScheme(
                description="Bearer token authentication",
                scheme="bearer",
                bearer_format="opaque",
            )
        )
    }
    security: list[dict[str, list[str]]] = [{"bearerAuth": []}]

    return AgentCard(
        name=settings.a2a_title,
        description=_build_agent_card_description(
            settings,
            runtime_profile,
            include_detailed_contracts=include_detailed_contracts,
        ),
        url=public_url,
        documentation_url=settings.a2a_documentation_url,
        version=settings.a2a_version,
        protocol_version=settings.a2a_protocol_version,
        preferred_transport=TransportProtocol.http_json,
        default_input_modes=list(DEFAULT_INPUT_MEDIA_MODES),
        default_output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=_build_agent_extensions(
                settings=settings,
                runtime_profile=runtime_profile,
                include_detailed_contracts=include_detailed_contracts,
            ),
        ),
        skills=_build_agent_skills(
            settings=settings,
            include_detailed_contracts=include_detailed_contracts,
        ),
        supports_authenticated_extended_card=True,
        additional_interfaces=[
            AgentInterface(transport=TransportProtocol.http_json, url=public_url),
            AgentInterface(transport=TransportProtocol.jsonrpc, url=public_url),
        ],
        security_schemes=security_schemes,
        security=security,
    )


def build_agent_card(
    settings: Settings,
    *,
    runtime_profile: RuntimeProfile | None = None,
) -> AgentCard:
    return _build_agent_card(
        settings,
        runtime_profile=runtime_profile,
        include_detailed_contracts=False,
    )


def build_authenticated_extended_agent_card(
    settings: Settings,
    *,
    runtime_profile: RuntimeProfile | None = None,
) -> AgentCard:
    return _build_agent_card(
        settings,
        runtime_profile=runtime_profile,
        include_detailed_contracts=True,
    )
