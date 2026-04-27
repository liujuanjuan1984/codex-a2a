from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
)
from a2a.utils.constants import TransportProtocol

from codex_a2a.auth import has_configured_auth_scheme
from codex_a2a.config import Settings
from codex_a2a.media_modes import (
    DEFAULT_INPUT_MEDIA_MODES,
    DEFAULT_OUTPUT_MEDIA_MODES,
    JSON_OUTPUT_MEDIA_MODES,
    JSON_RPC_INPUT_MEDIA_MODES,
    TEXT_OUTPUT_MEDIA_MODES,
)
from codex_a2a.profile.runtime import RuntimeProfile, build_runtime_profile

from .agent_card_extensions import build_agent_extensions


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

    codex_surfaces = [
        "Codex session-query",
        "thread lifecycle",
        "discovery",
        "interrupt recovery",
    ]
    if runtime_profile.turn_control_enabled:
        codex_surfaces.append("active-turn control")
    if runtime_profile.review_control_enabled:
        codex_surfaces.append("review control")
    if runtime_profile.exec_control_enabled:
        codex_surfaces.append("interactive exec")
    codex_surface_summary = ", ".join(codex_surfaces)
    summary = (
        "Supports HTTP+JSON and JSON-RPC transports, standard A2A messaging "
        "(SendMessage, SendStreamingMessage), authenticated extended Agent Card "
        "(GetExtendedAgentCard), task APIs (GetTask, ListTasks, CancelTask, "
        "SubscribeToTask), shared session-binding and streaming contracts, "
        f"{codex_surface_summary} extensions, shared interrupt callback "
        "extensions, a machine-readable compatibility profile, and a "
        "machine-readable wire contract."
    )
    parts: list[str] = [base, summary]
    parts.append(
        "Within one codex-a2a instance, all consumers share the same "
        "underlying Codex workspace/environment."
    )
    parts.append(
        "Authenticated endpoints accept statically configured bearer/basic "
        "credentials from the deployment auth registry."
    )
    parts.append(
        "Terminal task-subscription replay-once behavior is declared as a "
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


def _build_agent_skills(
    *,
    settings: Settings,
    runtime_profile: RuntimeProfile,
    include_detailed_contracts: bool,
) -> list[AgentSkill]:
    session_control_description = (
        "Start async Codex session turns and issue provider-private "
        "session command control methods."
    )
    if runtime_profile.session_shell_enabled:
        session_control_description = (
            "Start async Codex session turns and issue provider-private "
            "session command or shell helper methods for internal workflows."
        )
    if not include_detailed_contracts:
        skills = [
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
                description=session_control_description,
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
                id="codex.interrupt.recovery",
                name="Codex Interrupt Recovery",
                description=(
                    "Rediscover pending interrupt request_ids for the current authenticated "
                    "caller after reconnecting."
                ),
                tags=["codex", "interrupt", "recovery", "provider-private"],
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
        ]
        if runtime_profile.turn_control_enabled:
            skills.append(
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
                )
            )
        if runtime_profile.review_control_enabled:
            skills.extend(
                [
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
                ]
            )
        if runtime_profile.exec_control_enabled:
            skills.extend(
                [
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
            )
        return skills

    session_control_examples = [
        "Start an async session turn (method codex.sessions.prompt_async).",
        "Run a session command (method codex.sessions.command).",
    ]
    detailed_session_control_description = (
        "Start async session turns and issue session-scoped command methods "
        "via provider-private JSON-RPC."
    )
    if runtime_profile.session_shell_enabled:
        detailed_session_control_description = (
            "Start async session turns and issue session-scoped command or "
            "one-shot shell helper methods via provider-private JSON-RPC."
        )
        session_control_examples.append(
            "Run a one-shot shell snapshot for a session (method codex.sessions.shell)."
        )

    skills = [
        AgentSkill(
            id="codex.chat",
            name="Codex Chat",
            description=(
                "Handle SendMessage and SendStreamingMessage requests by routing text, "
                "file, and structured data parts to "
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
            description=detailed_session_control_description,
            tags=["codex", "sessions", "control", "commands"],
            examples=session_control_examples,
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
                "Resume a discovery watch task with SubscribeToTask.",
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
                "Resume a lifecycle watch task with SubscribeToTask.",
            ],
            input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
            output_modes=list(JSON_OUTPUT_MEDIA_MODES),
        ),
        AgentSkill(
            id="codex.interrupt.recovery",
            name="Codex Interrupt Recovery",
            description=(
                "Rediscover pending interrupt request_ids for the current authenticated "
                "caller via codex.interrupts.list."
            ),
            tags=["codex", "interrupt", "recovery"],
            examples=[
                (
                    "List active pending interrupts for the current caller "
                    "(method codex.interrupts.list)."
                ),
                "List only pending permission interrupts with type=permission.",
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
    ]
    if runtime_profile.turn_control_enabled:
        skills.append(
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
            )
        )
    if runtime_profile.review_control_enabled:
        skills.extend(
            [
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
                        "Resume a review watch task with SubscribeToTask.",
                    ],
                    input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                    output_modes=list(JSON_OUTPUT_MEDIA_MODES),
                ),
            ]
        )
    if runtime_profile.exec_control_enabled:
        skills.extend(
            [
                AgentSkill(
                    id="codex.exec.control",
                    name="Codex Exec Control",
                    description=(
                        "Start and control standalone interactive command execution via "
                        "codex.exec.start/write/resize/terminate for internal workflows."
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
                        "Resume an exec task stream with SubscribeToTask after codex.exec.start.",
                        (
                            "Read final exec result text from the completed task artifact "
                            "or status message."
                        ),
                    ],
                    input_modes=list(JSON_RPC_INPUT_MEDIA_MODES),
                    output_modes=list(TEXT_OUTPUT_MEDIA_MODES),
                ),
            ]
        )
    return skills


def _build_agent_card(
    settings: Settings,
    *,
    runtime_profile: RuntimeProfile | None,
    include_detailed_contracts: bool,
) -> AgentCard:
    public_url = settings.a2a_public_url.rstrip("/")
    runtime_profile = runtime_profile or build_runtime_profile(settings)
    security_schemes: dict[str, SecurityScheme] = {}
    security: list[dict[str, list[str]]] = []
    if has_configured_auth_scheme(settings, "bearer"):
        security_schemes["bearerAuth"] = SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                description="Bearer token authentication",
                scheme="bearer",
                bearer_format="opaque",
            )
        )
        requirement = SecurityRequirement()
        requirement.schemes["bearerAuth"].list.extend([])
        security.append(requirement)
    if has_configured_auth_scheme(settings, "basic"):
        security_schemes["basicAuth"] = SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                description="Basic authentication",
                scheme="basic",
            )
        )
        requirement = SecurityRequirement()
        requirement.schemes["basicAuth"].list.extend([])
        security.append(requirement)

    supported_interfaces = [
        AgentInterface(
            url=f"{public_url}/v1",
            protocol_binding=TransportProtocol.HTTP_JSON,
            protocol_version=settings.a2a_protocol_version,
        ),
        AgentInterface(
            url=public_url,
            protocol_binding=TransportProtocol.JSONRPC,
            protocol_version=settings.a2a_protocol_version,
        ),
    ]

    return AgentCard(
        name=settings.a2a_title,
        description=_build_agent_card_description(
            settings,
            runtime_profile,
            include_detailed_contracts=include_detailed_contracts,
        ),
        supported_interfaces=supported_interfaces,
        documentation_url=settings.a2a_documentation_url,
        version=settings.a2a_version,
        default_input_modes=list(DEFAULT_INPUT_MEDIA_MODES),
        default_output_modes=list(DEFAULT_OUTPUT_MEDIA_MODES),
        capabilities=AgentCapabilities(
            streaming=True,
            extended_agent_card=True,
            extensions=build_agent_extensions(
                settings=settings,
                runtime_profile=runtime_profile,
                include_detailed_contracts=include_detailed_contracts,
            ),
        ),
        skills=_build_agent_skills(
            settings=settings,
            runtime_profile=runtime_profile,
            include_detailed_contracts=include_detailed_contracts,
        ),
        security_schemes=security_schemes,
        security_requirements=security,
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
