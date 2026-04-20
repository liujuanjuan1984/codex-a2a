# Usage Guide

This guide covers runtime configuration, transport contracts, streaming/session/interrupt behavior, and client examples. [README.md](../README.md) stays at overview level, [maintainer-architecture.md](./maintainer-architecture.md) covers internal call chains and module boundaries, the stable extension URI/spec index lives in [extension-specifications.md](./extension-specifications.md), and compatibility promises live in [compatibility.md](./compatibility.md).

## Transport Contracts

- The service supports both transports:
  - HTTP+JSON (REST endpoints such as `/v1/message:send`)
  - JSON-RPC (`POST /`)
- Agent Card keeps `preferredTransport=HTTP+JSON` and also exposes JSON-RPC in `additional_interfaces`.
- The public Agent Card at `/.well-known/agent-card.json` is intentionally slimmed to the minimum discovery surface.
- Detailed provider-private contracts are available through the authenticated extended card:
  - preferred: JSON-RPC `agent/getAuthenticatedExtendedCard`
  - HTTP core route: `GET /v1/card`
  - compatibility route: `GET /agent/authenticatedExtendedCard`
- Agent Card responses publish `ETag` and `Cache-Control`; clients should revalidate instead of repeatedly fetching full payloads.
- Larger discovery documents support gzip compression on these HTTP GET routes:
  - `/.well-known/agent-card.json`
  - `/.well-known/agent.json`
  - `GET /v1/card`
  - `GET /agent/authenticatedExtendedCard`
  - `GET /openapi.json`
- Streaming and task routes do not rely on this gzip behavior.
- Payload schema is transport-specific and should not be mixed:
  - REST send payload usually uses `message.content` and role values like `ROLE_USER`
  - JSON-RPC `message/send` payload uses `params.message.parts` and role values `user` / `agent`
- The JSON-RPC entrypoint and authenticated extended card publish the explicit wire contract for the supported method set and unsupported-method error shape.

## Wire Contract

The full machine-readable wire contract is published through the authenticated extended card and OpenAPI metadata. The public Agent Card keeps only the minimum capability declarations needed for discovery.

Use it to answer:

- which JSON-RPC methods are part of the current A2A core baseline
- which JSON-RPC methods are custom extensions
- which methods are deployment-conditional rather than always available
- what error shape is returned for unsupported JSON-RPC methods

Current behavior:

- core JSON-RPC methods:
  - `message/send`
  - `message/stream`
  - `tasks/get`
  - `tasks/cancel`
  - `tasks/resubscribe`
- core HTTP endpoints:
  - `/v1/message:send`
  - `/v1/message:stream`
  - `/v1/tasks/{id}:subscribe`
- extension JSON-RPC methods are declared separately from the core baseline
- `codex.interrupts.list` is an always-on adapter-local recovery surface for pending interrupt request IDs
- `codex.sessions.shell` becomes deployment-conditional when `A2A_ENABLE_SESSION_SHELL=false`
- `codex.turns.steer` becomes deployment-conditional when `A2A_ENABLE_TURN_CONTROL=false`
- `codex.review.start` and `codex.review.watch` become deployment-conditional when `A2A_ENABLE_REVIEW_CONTROL=false`
- `codex.exec.*` becomes deployment-conditional when `A2A_ENABLE_EXEC_CONTROL=false`

Unsupported method contract:

- JSON-RPC error code: `-32601`
- error message: `Unsupported method: <method>`
- error data fields:
  - `type=METHOD_NOT_SUPPORTED`
  - `method`
  - `supported_methods`
  - `protocol_version`

Consumer guidance:

- Discover the current method set from Agent Card / OpenAPI before calling custom JSON-RPC methods.
- Fetch the authenticated extended card when you need the detailed method matrix, provider-private notes, or full extension params.
- Treat `supported_methods` in `error.data` as the runtime truth for the current deployment, especially when a deployment-conditional method is disabled.
- Treat the core A2A methods as the portable interoperability baseline.
- Treat `codex.*` methods plus `metadata.codex.directory` and `metadata.codex.execution` as a Codex-specific control plane for Codex-aware clients rather than generic A2A portability claims.
- See [extension-specifications.md](./extension-specifications.md) for the stable URI/spec index, and [compatibility.md](./compatibility.md) for compatibility promises.

## Compatibility Profile

The full machine-readable compatibility profile is published through the authenticated extended card and OpenAPI metadata. Its purpose is to declare:

- the stable A2A core interoperability baseline
- which shared extensions are intended to be reused across this repo family
- which Codex-specific JSON-RPC methods are product-specific extensions
- which extension surfaces are required runtime metadata contracts
- which methods are deployment-conditional rather than always available

Current profile shape:

- `profile_id=codex-a2a-single-tenant-coding-v1`
- deployment profile:
  - `id=single_tenant_shared_workspace`
  - `single_tenant=true`
  - `shared_workspace_across_consumers=true`
  - `tenant_isolation=none`
- runtime features:
  - `directory_binding.allow_override=true|false`
  - `directory_binding.scope=workspace_root_or_descendant|workspace_root_only`
  - `session_shell.enabled=true|false`
  - `session_shell.availability=enabled|disabled`
  - `turn_control.enabled=true|false`
  - `turn_control.availability=enabled|disabled`
  - `review_control.enabled=true|false`
  - `review_control.availability=enabled|disabled`
  - `exec_control.enabled=true|false`
  - `exec_control.availability=enabled|disabled`
  - `interrupts.request_ttl_seconds=<int>`
  - `service_features.streaming.enabled=true`
  - `service_features.health_endpoint.enabled=true|false`
  - `execution_environment.sandbox.mode=unknown|read-only|workspace-write|danger-full-access`
  - `execution_environment.sandbox.filesystem_scope=unknown|none|workspace_root|workspace_root_or_descendant|configured_roots|full_filesystem`
  - `execution_environment.network.access=unknown|disabled|enabled|restricted`
  - `execution_environment.approval.policy=unknown|never|on-request|on-failure|untrusted-only`
  - `execution_environment.write_access.scope=unknown|none|workspace_root|workspace_root_or_descendant|configured_roots|full_filesystem`
- runtime context:
  - `project=<optional>`
  - `workspace_root=<optional>`
  - `provider_id=<optional>`
  - `model_id=<optional>`
  - `agent=<optional>`
  - `variant=<optional>`
- core JSON-RPC methods:
  - `message/send`
  - `message/stream`
  - `tasks/get`
  - `tasks/cancel`
  - `tasks/resubscribe`
- core HTTP endpoints:
  - `/v1/message:send`
  - `/v1/message:stream`
  - `/v1/tasks/{id}:subscribe`

Retention guidance:

- Treat core methods as the generic client interoperability baseline.
- Treat this deployment as a single-tenant, shared-workspace coding profile.
- Treat shared session-binding and streaming metadata contracts as required for the current deployment model; they are not optional documentation-only hints.
- Treat `urn:a2a:*` extension URIs in this repository as shared extension conventions used across this repo family, not as claims that they are part of the A2A core baseline.
- Treat `a2a.interrupt.*` methods as shared extensions.
- Treat `codex.*` methods plus `metadata.codex.directory` and `metadata.codex.execution` as Codex-specific extensions or provider-private operational surfaces rather than portable A2A baseline capabilities.
- Treat `codex.sessions.shell` as a deployment-conditional, provider-private shell snapshot helper. Discover it from the declared compatibility profile and extension contracts before calling it.
- Treat `codex.sessions.shell` as a one-shot shell snapshot surface. It is useful for tightly controlled internal workflows, but it is not an interactive shell session and does not imply PTY lifecycle support.
- Treat `codex.interrupts.list` as an adapter-local recovery surface for rediscovering active pending interrupt request IDs after reconnecting.
- Treat `codex.turns.steer`, `codex.review.*`, and `codex.exec.*` as deployment-aware provider-private controls. Discover them from the authenticated extended card or OpenAPI before calling them.
- Treat `codex.exec.*` as the standalone interactive exec surface for internal or tightly controlled deployments. Use it for stdin write, PTY resize, and terminate flows instead of inferring those semantics from `codex.sessions.shell`.
- Default deployment posture keeps `codex.sessions.shell`, `codex.review.*`, and `codex.exec.*` disabled unless a deployment intentionally opts into them. `codex.turns.steer` is enabled by default but remains provider-private and can still be disabled with `A2A_ENABLE_TURN_CONTROL=false`.
- Generic A2A clients should remain usable without the `codex.*` control plane. Opt into those methods only when you are intentionally integrating with Codex-specific workflows such as session continuation, discovery-backed mentions, or interactive exec.
- Treat `execution_environment.*` as deployment-configured discovery metadata. It does not promise per-request snapshots of temporary approvals, escalations, or host-side runtime mutations.

Extension boundary principles:

- Expose provider-specific capabilities through A2A only when they still fit the adapter boundary. The adapter may document, validate, route, and normalize stable upstream-facing behavior, but it should not become a general replacement for upstream private runtime internals or host-level control planes.
- Default new `codex.*` methods to provider-private status. Do not present them as portable A2A baseline capabilities unless they truly match shared protocol semantics.
- Prefer read-only discovery, stable compatibility surfaces, and low-risk control methods before introducing stronger mutating or destructive operations.
- Map results to A2A core objects only when the upstream payload is a stable, low-ambiguity read projection such as session-to-`Task`, turn-to-`Task`, or message-to-`Message`. Otherwise prefer provider-private summary envelopes or watch-task payloads.
- Treat upstream internal execution mechanisms, including active-turn steering, standalone exec runtime controls, reviewer internals, subtask/subagent fan-out, and task-tool internals, as provider-private runtime behavior. The adapter may expose passthrough compatibility and observable output metadata, but should not promote those internals into a default A2A orchestration API.
- Before implementing a new provider-private extension, answer all of the following explicitly:
  - what client value is added beyond the existing chat/session flow?
  - is the upstream behavior stable enough to document as a maintained contract?
  - should the surface remain provider-private, deployment-conditional, or not be exposed at all?
  - are authorization, workspace/session ownership, and destructive-side-effect boundaries clear enough to enforce?
  - can the result shape be expressed without overfitting provider internals into fake A2A core semantics?

Current implementation note:

- The compatibility profile is declarative. It does not introduce a global runtime `core-only` switch; request-time `A2A-Version` negotiation is limited to the protocol lines and gaps published in the profile.
- This is intentional: current shared session/stream/interrupt behavior is part of the deployed interoperability contract, so a blanket runtime profile split would be misleading without broader wire-level changes.
- For compatibility policy and stability expectations, use [compatibility.md](./compatibility.md) as the normative repo document rather than this usage guide.

## Environment Variables

Use the grouped sections below as the deployment-first reading order:

- Start with the required auth token.
- Then configure the common A2A runtime surface and service identity.
- If you use peer calls, configure the outbound A2A client defaults next.
- Then set the upstream Codex defaults.
- Only after that reach for advanced runtime toggles, advanced Codex overrides, or discovery-only metadata.

### Required Configuration

- Configure inbound auth through `A2A_STATIC_AUTH_CREDENTIALS`.
- The service fails fast if the static auth registry is missing or contains no enabled credentials.

### Common Runtime Configuration (A2A)

- `A2A_HOST`: bind host, default `127.0.0.1`
- `A2A_PORT`: bind port, default `8000`
- `A2A_PUBLIC_URL`: externally reachable A2A URL prefix, default `http://127.0.0.1:8000`
- `A2A_DATABASE_URL`: SQLAlchemy async database URL. Defaults to SQLite under `${CODEX_WORKSPACE_ROOT}/.codex-a2a/codex-a2a.db`.
- `A2A_DATABASE_URL` also owns the adapter-managed runtime-state schema lifecycle. On startup, `codex-a2a` auto-creates the runtime-state tables, records a schema version for the `runtime_state` scope, and applies in-place migrations for those tables only.
- The adapter-managed runtime-state schema is limited to `a2a_session_bindings`, `a2a_session_owners`, `a2a_pending_session_claims`, `a2a_pending_interrupt_requests`, and `a2a_schema_version`. It does not own the A2A SDK task-store tables or any upstream Codex/provider-local state.
- For deployment-specific durability constraints and migration-scope boundaries, see [compatibility.md](./compatibility.md).
- `A2A_LOG_LEVEL`: `DEBUG/INFO/WARNING/ERROR`, default `WARNING`
- `A2A_LOG_PAYLOADS`: log A2A/Codex payload bodies, default `false`
- `A2A_LOG_BODY_LIMIT`: payload log body size limit, default `0` (no truncation)
- `A2A_TITLE`: agent name, default `Codex A2A`
- `A2A_DESCRIPTION`: agent description exposed on Agent Card and docs surfaces
- `A2A_VERSION`: agent version string
- `A2A_PROJECT`: optional project label injected into examples and discovery metadata
- `A2A_PROTOCOL_VERSION`: advertised A2A protocol version, default `0.3.0`
- `A2A_SUPPORTED_PROTOCOL_VERSIONS`: comma-separated request negotiation lines, default `0.3,1.0`
- `A2A_DOCUMENTATION_URL`: optional external documentation URL exposed on Agent Card
- `A2A_STATIC_AUTH_CREDENTIALS`: JSON array of static inbound credentials. Supports multiple `bearer` and `basic` entries, each with a stable `principal`; `bearer` entries must declare `principal`, while `basic` entries derive `principal` from `username`.

### Outbound A2A Client Defaults

These settings affect peer calls made through `codex-a2a call` or the embedded `a2a_call(...)` tool surface.

- `A2A_CLIENT_TIMEOUT_SECONDS`: default outbound request timeout, default `30.0`
- `A2A_CLIENT_CARD_FETCH_TIMEOUT_SECONDS`: timeout for outbound Agent Card fetches, default `5.0`
- `A2A_CLIENT_USE_CLIENT_PREFERENCE`: whether outbound transport negotiation should prefer local client ordering, default `false`
- `A2A_CLIENT_SUPPORTED_TRANSPORTS`: comma-separated outbound transport preference list, default `JSONRPC,HTTP+JSON`
- `A2A_CLIENT_BEARER_TOKEN`: optional bearer token for the target peer service
- `A2A_CLIENT_BASIC_AUTH`: optional Basic auth credential for the target peer service when bearer auth is not configured

### Upstream Codex Configuration

These variables are forwarded to the local `codex app-server` subprocess.

- `CODEX_WORKSPACE_ROOT`: default Codex workspace root (optional)
- `CODEX_CLI_BIN`: Codex CLI binary path, default `codex`
- `CODEX_MODEL`: default Codex model, default `gpt-5.1-codex`
- `CODEX_APPROVAL_POLICY`: default approval policy (`never`, `on-request`, etc.)
- `CODEX_SANDBOX_MODE`: default sandbox mode (`danger-full-access`, `read-only`, etc.)
- `CODEX_TIMEOUT`: request timeout in seconds, default `120`
- `CODEX_WEB_SEARCH`: default Codex web search mode (`live`, `disabled`)

### Advanced Runtime Settings

- `A2A_ENABLE_HEALTH_ENDPOINT`: enable the authenticated lightweight `/health` probe, default `true`
- `A2A_ENABLE_SESSION_SHELL`: expose `codex.sessions.shell` on JSON-RPC extensions, default `false`
- `A2A_ENABLE_TURN_CONTROL`: expose `codex.turns.steer` on JSON-RPC extensions, default `true`
- `A2A_ENABLE_REVIEW_CONTROL`: expose `codex.review.start` and `codex.review.watch` on JSON-RPC extensions, default `false`
- `A2A_ENABLE_EXEC_CONTROL`: expose `codex.exec.*` on JSON-RPC extensions, default `false`
- `A2A_ALLOW_DIRECTORY_OVERRIDE`: allow `metadata.codex.directory` overrides within the configured workspace boundary, default `true`
- `A2A_SESSION_CACHE_TTL_SECONDS`: in-memory TTL for session mapping, default `3600`
- `A2A_SESSION_CACHE_MAXSIZE`: max local process session-cache entries, default `10000`
- `A2A_CANCEL_ABORT_TIMEOUT_SECONDS`: timeout for task cancellation cleanup, default `1.0`
- `A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS`: threshold before the service emits a stream idle diagnostic log, default `60.0`
- `A2A_INTERRUPT_REQUEST_TTL_SECONDS`: TTL for pending interrupt callbacks before they expire, default `3600`

### Advanced Upstream Codex Overrides

- `CODEX_APP_SERVER_LISTEN`: Codex app-server listen target, default `stdio://`
- `CODEX_MODEL_ID`: per-turn model override passed to `turn/start`
- `CODEX_MODEL_REASONING_EFFORT`: explicit reasoning effort override passed to `codex app-server`
- `CODEX_MODEL_REASONING_SUMMARY`: reasoning summary mode passed to `codex app-server`
- `CODEX_MODEL_VERBOSITY`: model verbosity override passed to `codex app-server`
- `CODEX_PROFILE`: Codex profile name passed to `codex app-server`
- `CODEX_REVIEW_MODEL`: review model override passed to `codex app-server`
- `CODEX_TIMEOUT_STREAM`: explicit stream-turn timeout; unset means no dedicated stream timeout override
- `CODEX_SANDBOX_WORKSPACE_WRITE_WRITABLE_ROOTS`: comma-separated writable roots for workspace-write mode
- `CODEX_SANDBOX_WORKSPACE_WRITE_NETWORK_ACCESS`: workspace-write network access flag
- `CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_SLASH_TMP`: workspace-write `/tmp` exclusion flag
- `CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_TMPDIR_ENV_VAR`: workspace-write `$TMPDIR` exclusion flag

### Discovery-only Metadata

- `A2A_EXECUTION_*`: declarative execution-environment metadata published through discovery surfaces; does not control runtime startup.
- `CODEX_PROVIDER_ID`: deployment metadata only
- `CODEX_AGENT`: deployment metadata only
- `CODEX_VARIANT`: deployment metadata only

### Full Configuration Matrix

| Variable | Description |
| :--- | :--- |
| `A2A_STATIC_AUTH_CREDENTIALS` | Static inbound auth registry |
| `A2A_HOST` | Bind host |
| `A2A_PORT` | Bind port |
| `A2A_PUBLIC_URL` | Public URL prefix |
| `A2A_DATABASE_URL` | Persistence DB URL |
| `A2A_LOG_LEVEL` | Log level |
| `A2A_LOG_PAYLOADS` | Log bodies |
| `A2A_LOG_BODY_LIMIT` | Body log limit |
| `A2A_TITLE` | Agent title |
| `A2A_DESCRIPTION` | Agent description |
| `A2A_VERSION` | Agent version |
| `A2A_PROJECT` | Project label |
| `A2A_PROTOCOL_VERSION` | Protocol version |
| `A2A_SUPPORTED_PROTOCOL_VERSIONS` | Supported protocol versions |
| `A2A_DOCUMENTATION_URL` | Documentation URL |
| `A2A_ENABLE_HEALTH_ENDPOINT` | Enable /health |
| `A2A_ENABLE_SESSION_SHELL` | Enable session shell |
| `A2A_ENABLE_TURN_CONTROL` | Enable turn control |
| `A2A_ENABLE_REVIEW_CONTROL` | Enable review control |
| `A2A_ENABLE_EXEC_CONTROL` | Enable interactive exec |
| `A2A_ALLOW_DIRECTORY_OVERRIDE` | Allow cwd override |
| `A2A_SESSION_CACHE_TTL_SECONDS` | Session cache TTL |
| `A2A_SESSION_CACHE_MAXSIZE` | Session cache max size |
| `A2A_CANCEL_ABORT_TIMEOUT_SECONDS` | Cancel timeout |
| `A2A_STREAM_IDLE_DIAGNOSTIC_SECONDS` | Stream idle log threshold |
| `A2A_CLIENT_BEARER_TOKEN` | Outbound bearer token |
| `A2A_CLIENT_BASIC_AUTH` | Outbound basic auth |
| `A2A_CLIENT_TIMEOUT_SECONDS` | Outbound timeout |
| `A2A_CLIENT_CARD_FETCH_TIMEOUT_SECONDS` | Card fetch timeout |
| `A2A_CLIENT_USE_CLIENT_PREFERENCE` | Transport preference |
| `A2A_CLIENT_SUPPORTED_TRANSPORTS` | Supported transports |
| `A2A_INTERRUPT_REQUEST_TTL_SECONDS` | Interrupt TTL |
| `A2A_EXECUTION_SANDBOX_MODE` | Discovery sandbox mode |
| `A2A_EXECUTION_SANDBOX_FILESYSTEM_SCOPE` | Discovery FS scope |
| `A2A_EXECUTION_SANDBOX_WRITABLE_ROOTS` | Discovery writable roots |
| `A2A_EXECUTION_NETWORK_ACCESS` | Discovery network access |
| `A2A_EXECUTION_NETWORK_ALLOWED_DOMAINS` | Discovery net allowlist |
| `A2A_EXECUTION_APPROVAL_POLICY` | Discovery approval policy |
| `A2A_EXECUTION_APPROVAL_ESCALATION_BEHAVIOR` | Discovery escalation |
| `A2A_EXECUTION_WRITE_ACCESS_SCOPE` | Discovery write scope |
| `A2A_EXECUTION_WRITE_OUTSIDE_WORKSPACE` | Discovery write outside |
| `CODEX_CLI_BIN` | Codex CLI path |
| `CODEX_APP_SERVER_LISTEN` | Codex listen target |
| `CODEX_WORKSPACE_ROOT` | Workspace root |
| `CODEX_MODEL` | Default model |
| `CODEX_MODEL_ID` | Turn model override |
| `CODEX_MODEL_REASONING_EFFORT` | Reasoning effort |
| `CODEX_MODEL_REASONING_SUMMARY` | Reasoning summary mode |
| `CODEX_MODEL_VERBOSITY` | Model verbosity |
| `CODEX_PROFILE` | Codex profile |
| `CODEX_APPROVAL_POLICY` | Approval policy |
| `CODEX_SANDBOX_MODE` | Sandbox mode |
| `CODEX_SANDBOX_WORKSPACE_WRITE_WRITABLE_ROOTS` | Writable roots |
| `CODEX_SANDBOX_WORKSPACE_WRITE_NETWORK_ACCESS` | Network access flag |
| `CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_SLASH_TMP` | Exclude /tmp |
| `CODEX_SANDBOX_WORKSPACE_WRITE_EXCLUDE_TMPDIR_ENV_VAR` | Exclude $TMPDIR |
| `CODEX_WEB_SEARCH` | Web search mode |
| `CODEX_REVIEW_MODEL` | Review model |
| `CODEX_TIMEOUT` | Request timeout |
| `CODEX_TIMEOUT_STREAM` | Stream turn timeout |
| `CODEX_PROVIDER_ID` | Provider ID metadata |
| `CODEX_AGENT` | Agent metadata |
| `CODEX_VARIANT` | Variant metadata |

For more details on each variable, see the internal configuration schema in `src/codex_a2a/config.py`.

Configuration note:
- The service configuration layer only accepts `CODEX_*` names for Codex-facing settings.
- Outbound auth prefers `A2A_CLIENT_BEARER_TOKEN` when both bearer and basic credentials are configured; otherwise it uses `A2A_CLIENT_BASIC_AUTH`.

YOLO-equivalent execution note:
- `codex-a2a` does not expose a separate `--yolo` flag or `YOLO` environment variable.
- To start the underlying Codex app-server with YOLO-equivalent behavior, configure:
  - `CODEX_APPROVAL_POLICY=never`
  - `CODEX_SANDBOX_MODE=danger-full-access`
- These values are forwarded to `codex app-server` as `-c approval_policy=...` and `-c sandbox_mode=...`.
- `A2A_EXECUTION_*` variables are declarative discovery metadata and do not control Codex subprocess startup.

Codex prerequisite note:
- `codex-a2a` assumes the local `codex` runtime is already usable.
- Install and verify the `codex` CLI itself before starting this server.
- Provider selection, login state, and upstream API keys remain Codex-side prerequisites.
- Service startup fails fast when the local `codex` runtime is missing or cannot initialize.

## Released CLI Self-Start

For a single user or an existing workspace root, prefer the published CLI instead of repository scripts. The abbreviated quick-start stays in [README.md](../README.md); this section keeps the fuller runtime example and operational notes.

Install once:

```bash
uv tool install codex-a2a
```

Apply the same Codex prerequisites from [README.md](../README.md) before starting the runtime. This guide keeps the fuller example with explicit model and timeout overrides.

Run against a workspace root:

```bash
DEMO_BEARER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(24))')"
A2A_STATIC_AUTH_CREDENTIALS='[{"id":"local-bearer","scheme":"bearer","token":"'"${DEMO_BEARER_TOKEN}"'","principal":"automation"}]' \
A2A_HOST=127.0.0.1 \
A2A_PORT=8000 \
A2A_PUBLIC_URL=http://127.0.0.1:8000 \
A2A_DATABASE_URL=sqlite+aiosqlite:////abs/path/to/workspace/.codex-a2a/codex-a2a.db \
CODEX_WORKSPACE_ROOT=/abs/path/to/workspace \
CODEX_MODEL=gpt-5.1-codex \
CODEX_APPROVAL_POLICY=never \
CODEX_SANDBOX_MODE=danger-full-access \
CODEX_MODEL_REASONING_EFFORT=high \
CODEX_WEB_SEARCH=live \
CODEX_TIMEOUT=300 \
codex-a2a
```

Notes:

- `CODEX_WORKSPACE_ROOT` should point at the workspace root you want Codex to operate in.
- If `A2A_DATABASE_URL` is omitted, `codex-a2a` defaults to `${CODEX_WORKSPACE_ROOT}/.codex-a2a/codex-a2a.db` when a workspace root is configured.
- For the default SQLite + WAL profile, prefer a local disk path over network-mounted or sync-managed directories.
- `codex-a2a` launches the Codex app-server subprocess itself; no separate `codex serve` step is required.
- Upgrade the installed CLI with `uv tool upgrade codex-a2a`.

## Source-Based Development Start

Use the source tree directly only for development, debugging, or validation of unreleased changes:

```bash
uv sync --all-extras
export DEMO_BEARER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(24))')"
export A2A_STATIC_AUTH_CREDENTIALS='[{"id":"local-bearer","scheme":"bearer","token":"'"${DEMO_BEARER_TOKEN}"'","principal":"automation"}]'
CODEX_WORKSPACE_ROOT=/abs/path/to/workspace uv run codex-a2a
```

This path is for contributors. End users should prefer the released CLI path described first in [README.md](../README.md) and above in this guide.

## Service Behavior

### Health, Auth, and Deployment Boundary

- `GET /health` is a lightweight authenticated status probe. It requires the same configured inbound auth as other protected endpoints and returns service status plus a structured `profile` summary; it does not call upstream Codex.
- Protected routes accept configured inbound `Authorization: Bearer <token>` and/or `Authorization: Basic <base64(username:password)>` credentials. The public Agent Card endpoints are public; authenticated extended card routes still require inbound auth.
- Static credential registry mode is the only supported inbound auth shape. It lets deployments define multiple bearer tokens and/or multiple Basic credentials with stable `principal` values.
- Stable `principal` values back runtime ownership checks. This avoids tying session, watch, or exec ownership to a bearer token hash that changes during token rotation.
- Capability gating stays intentionally small:
  - `codex.sessions.shell` requires `session_shell`
  - `codex.turns.steer` requires `turn_control`
  - `codex.exec.*` requires `exec_control`
  - Basic credentials grant all three capabilities by default unless the registry entry overrides capabilities
  - bearer credentials do not gain those capabilities unless the static credential entry explicitly grants them
- Within one `codex-a2a` instance, all consumers share the same underlying Codex workspace/environment. This deployment model is not tenant-isolated by default.

### Session and Task Behavior

- The service forwards A2A `message:send` to Codex session/message calls.
- Streaming is always enabled for this service surface. `/v1/message:stream` and JSON-RPC `message/stream` are compatibility-sensitive core capabilities rather than deployment-time toggles.
- `codex.sessions.shell` is a session-scoped shell helper for ownership, attribution, and traceability in internal deployments. It keeps `session_id` in the A2A contract, but the underlying execution still uses Codex `command/exec` rather than resuming or creating an upstream Codex thread.
- `codex.sessions.shell` returns a one-shot shell snapshot only. It does not expose PTY lifecycle methods such as stdin write, resize, or terminate, and should be treated as a bounded helper rather than a general session shell.
- `codex.exec.start`, `codex.exec.write`, `codex.exec.resize`, and `codex.exec.terminate` expose a standalone interactive `command/exec` runtime when `A2A_ENABLE_EXEC_CONTROL=true`. This surface is intended for internal or tightly controlled deployments where interactive terminal control is an explicit part of the adapter contract. `codex.exec.start` returns process/task handles immediately, while stdout/stderr deltas and the final result flow through normal A2A task streaming and `tasks/resubscribe`.
- Rich input is supported on two surfaces:
  - `codex.sessions.prompt_async.request.parts[]` accepts `text`, `image`, `mention`, and `skill`
  - core A2A `message/send` and `message/stream` keep standard A2A parts and map `TextPart`, image `FilePart`, and `DataPart(data={"type":"mention"|"skill", ...})` into Codex turn input
- Agent Card media modes reflect that stable core message surface: default input modes are `text/plain`, `image/*`, and `application/json`; default output modes are `text/plain` and `application/json`.
- The authenticated extended Agent Card also decomposes provider-private JSON-RPC surfaces into narrower skills: `codex.sessions.query`, `codex.sessions.control`, `codex.discovery.query`, `codex.discovery.watch`, `codex.threads.control`, `codex.threads.watch`, `codex.turns.control`, `codex.review.control`, `codex.exec.control`, `codex.exec.stream`, and `codex.interrupt.callback`.
- `codex.sessions.shell`, `codex.turns.control`, `codex.review.*`, and `codex.exec.*` only appear in the authenticated extended card when their deployment toggles are enabled.
- Those provider-private skills use narrower `output_modes` where practical: query/control/watch handle surfaces declare `application/json` when their primary contract is a structured JSON-RPC result or `DataPart` watch payload, while `codex.exec.stream` declares `text/plain` because stdout/stderr deltas and terminal summaries are emitted as `TextPart`.
- `codex.sessions.control` intentionally remains mixed: `codex.sessions.prompt_async` returns a structured handle, while `codex.sessions.command` and `codex.sessions.shell` return A2A message items that contain `TextPart`.
- On the core chat surface, the `application/json` input mode is intentionally narrower than arbitrary JSON: only `DataPart(type=mention|skill)` is part of the declared stable contract.
- Image input maps to upstream `turn/start.input[].type=input_image`.
- `mention.path` and `skill.path` are forwarded verbatim. The service does not guess app or plugin identifiers from display names.
- `local_image` is not part of the current declared stable rich-input contract.
- Session query projections currently use the upstream Codex `session_id` as the A2A `contextId`. This is intentional for the current deployment model: `contextId` and `metadata.shared.session.id` refer to the same upstream session identity, and the contract declares that equality explicitly.
- Completed chat turns are persisted as `completed`; `input-required` is reserved for active interrupt asks that still need a reply.
- Non-streaming requests return a `Task` directly.
- Non-streaming `message:send` responses may include normalized token usage at `Task.metadata.shared.usage` with the same field schema.
- `tasks/resubscribe` remains part of the core A2A method baseline, but this deployment's terminal-task replay-once policy is a declared service-level behavior rather than a generic A2A guarantee.
- Task persistence also applies a service-level resilience policy: once a task has been durably stored in a terminal state, later conflicting writes are dropped instead of overwriting that terminal snapshot.

### Streaming and Interrupt Contract

- Streaming (`/v1/message:stream`) emits incremental `TaskArtifactUpdateEvent` and then `TaskStatusUpdateEvent(final=true)`.
- If task persistence fails while processing a request, the service maps that failure to a stable failed task or failed final status instead of leaking raw task-store exceptions.
- Those task-store failure surfaces use `metadata.codex.error` with `type=TASK_STORE_UNAVAILABLE` and an `operation` field such as `get` or `save`.
- Stream artifacts carry `artifact.metadata.shared.stream.block_type` with values `text`, `reasoning`, and `tool_call`.
- The published `urn:a2a:stream-hints/v1` contract also declares the emitted A2A part type per block: `text` and `reasoning` use `TextPart`, while `tool_call` uses `DataPart`.
- All chunks share one stream artifact ID and preserve original timeline via `artifact.metadata.shared.stream.sequence`. Timeline identity fields such as `message_id`, `event_id`, and `source` are emitted under `metadata.shared.stream`.
- Session projections are normalized under `metadata.shared.session`, with `id` as the canonical field and optional `title` when the upstream surface provides one. The corresponding leaf fields are `metadata.shared.session.id` and `metadata.shared.session.title`.
- A final snapshot is emitted only when stream chunks did not already produce the same final text.
- Stream routing is schema-first: the service classifies chunks primarily by Codex `part.type` plus `part_id` state rather than inline text markers.
- `message.part.delta` and `message.part.updated` are merged per `part_id`; out-of-order deltas are buffered and replayed when the corresponding `part.updated` arrives.
- `text` and `reasoning` chunks are emitted as `TextPart`, while `tool_call` chunks are emitted as `DataPart` with a normalized structured payload.
- Legacy stringified JSON tool payloads are rejected; the stream contract only accepts structured `DataPart(data={...})` payloads.
- Core `message/send` and `message/stream` honor `configuration.acceptedOutputModes` for emitted A2A parts. When a client accepts `text/plain` but not `application/json`, structured `DataPart` payloads are downgraded to compact text instead of being emitted as raw `DataPart`.
- Core chat also validates explicit `acceptedOutputModes` up front. Requests that do not accept any declared chat output mode are rejected, and current chat requests must still accept `text/plain`.
- `application/json` is additive structured-output support, not a promise that every natural-language reply can be losslessly re-encoded as a JSON `DataPart`. Clients that expect ordinary assistant prose should continue accepting `text/plain`.
- Negotiated output modes are persisted with the task as soon as the task state is materialized, including artifact-first streams before any later status update arrives.
- That negotiated output surface is treated as part of the task lifecycle: `tasks/get`, `tasks/resubscribe`, and push notifications continue using the task's negotiated output modes instead of reverting to raw stored `DataPart`.
- To avoid character-level event floods, the service performs light server-side aggregation before emitting `text` and `reasoning` updates: `text` flushes at `120 chars or 200ms`, `reasoning` flushes at `240 chars or 350ms`, and both flush immediately on block switches, `tool_call`, and request completion boundaries.
- Final status event metadata may include normalized token usage at `metadata.shared.usage` with fields like `input_tokens`, `output_tokens`, `total_tokens`, optional `metadata.shared.usage.reasoning_tokens`, `metadata.shared.usage.cache_tokens.read_tokens`, `metadata.shared.usage.cache_tokens.write_tokens`, `metadata.shared.usage.raw`, and optional `cost`.
- Interrupt lifecycle is explicit:
  - asked events (`permission.asked` / `question.asked` / `permissions.asked` / `elicitation.asked`) are mapped to `TaskStatusUpdateEvent(final=false, state=input-required)` with `metadata.shared.interrupt.phase=asked`
  - resolved events (`permission.replied` / `question.replied` / `question.rejected` / `permissions.replied` / `elicitation.replied` / `elicitation.rejected`) are mapped to `TaskStatusUpdateEvent(final=false, state=working)` with `metadata.shared.interrupt.phase=resolved` and `metadata.shared.interrupt.resolution=replied|rejected`
- Duplicate or unknown resolved events are suppressed by `request_id`.
- For Codex app-server approval and `tool/requestUserInput` requests, user-visible approval/question/permissions/elicitation details are normalized into `metadata.shared.interrupt.details`, including readable `display_message`, resolved `patterns`, requested permission subsets, elicitation form/url payloads, and `questions` when available.
- HTTP streaming responses send transport-level SSE ping comments on a default keepalive interval from the underlying SDK / `sse-starlette` response without adding synthetic A2A business events.
- Interrupt status events no longer mirror the asked payload under `metadata.codex.interrupt`; downstream consumers should treat `metadata.shared.interrupt` as the single interrupt rendering contract.

### Tool Call Payload Contract

- The same shape is published in the machine-readable streaming extension contract under `tool_call_payload_contract`.

| `kind` | Required fields | Optional fields | Notes |
| --- | --- | --- | --- |
| `state` | `kind` | `source_method`, `call_id`, `tool`, `status`, `title`, `subtitle`, `input`, `output`, `error` | Used for structured tool state snapshots. A payload that contains only `kind=state` is invalid and is suppressed. |
| `output_delta` | `kind`, `output_delta` | `source_method`, `call_id`, `tool`, `status` | Used for raw tool output text increments. `output_delta` is preserved verbatim and may contain spaces or trailing newlines. |

`codex app-server` lifecycle events such as `item/started` and `item/completed` are normalized into `kind=state`; `item/*/outputDelta` notifications are normalized into `kind=output_delta`.

Examples:

```json
{"kind":"state","tool":"bash","call_id":"call-1","status":"running"}
```

```json
{"kind":"output_delta","source_method":"commandExecution","tool":"bash","call_id":"call-1","status":"running","output_delta":"Passed\n"}
```
### Directory and Error Handling

- For validation failures, missing context (`task_id`/`context_id`), or internal errors, the service attempts to return standard A2A failure events via `event_queue`.
- Failure events include concrete error details with `failed` state.
- Clients can pass `metadata.codex.directory`, but it must stay inside `${CODEX_WORKSPACE_ROOT}` (or service runtime root if not configured).
- Clients can also pass `metadata.codex.execution` with `model`, `effort`, `summary`, and `personality`.
- `metadata.codex.execution` is validated as a structured object. Invalid fields fail fast instead of being silently ignored.
- `metadata.codex.execution` applies only to request flows that create or continue Codex turns. It does not widen the standalone shell or interactive exec contracts.
- All paths are normalized with `realpath` to prevent `..` or symlink boundary bypass.
- If `A2A_ALLOW_DIRECTORY_OVERRIDE=false`, only the default directory is accepted.
## Authentication Setup For Local Examples

For local development examples, prefer generating a temporary token once and reusing it in the static auth registry plus the following request examples:

```bash
export DEMO_BEARER_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(24))')"
export A2A_STATIC_AUTH_CREDENTIALS='[{"id":"local-bearer","scheme":"bearer","token":"'"${DEMO_BEARER_TOKEN}"'","principal":"automation"}]'
```

Then reference the token in request examples as:

```bash
-H "Authorization: Bearer ${DEMO_BEARER_TOKEN}"
```

## Session Continuation Contract

To continue a historical Codex session, include this metadata key in each invoke request:

- `metadata.shared.session.id`: target Codex session ID

Server behavior:

- If provided, the request is sent to that exact Codex session.
- If omitted, a new session is created and cached by `(identity, contextId) -> session_id`.

Minimal example:

```bash
curl -sS http://127.0.0.1:8000/v1/message:send \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "message": {
      "messageId": "msg-continue-1",
      "role": "ROLE_USER",
      "content": [{"text": "Continue the previous session and restate the key conclusion."}]
    },
    "metadata": {
      "shared": {
        "session": {
          "id": "<session_id>"
        }
      }
    }
  }'
```

## Codex Session Query (A2A Extension)

This service exposes Codex session list and message-history queries via A2A JSON-RPC extension methods (default endpoint: `POST /`). No extra custom REST endpoint is introduced.

- Trigger: call extension methods through A2A JSON-RPC
- Auth: same `Authorization: Bearer <token>`
- Privacy guard: when `A2A_LOG_PAYLOADS=true`, request/response bodies are still suppressed for `method=codex.sessions.*`
- Endpoint discovery: prefer `additional_interfaces[]` with `transport=jsonrpc` from Agent Card
- Result format:
  - `result.items` is always an array of A2A standard objects
  - session list => `Task` with `status.state=completed`
  - message history => `Message`
  - limit pagination defaults to `20` items and rejects values above `100`
  - pagination behavior is mixed: `codex.sessions.list` forwards `limit` upstream, while `codex.sessions.messages.list` applies the limit locally
  - `codex.sessions.messages.list` enforces `limit` locally after mapping the upstream thread history into A2A messages, keeping the most recent N messages while preserving their original order
  - canonical session metadata is exposed at `metadata.shared.session`
  - raw upstream payload is preserved at `metadata.codex.raw`
  - session title is available at `metadata.shared.session.title`

### Session List (`codex.sessions.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "codex.sessions.list",
    "params": {"limit": 20}
  }'
```

### Session Messages (`codex.sessions.messages.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "codex.sessions.messages.list",
    "params": {
      "session_id": "<session_id>",
      "limit": 20
    }
  }'
```

## Codex Discovery (A2A Extension)

This service exposes read-only Codex discovery methods through JSON-RPC:

- `codex.discovery.skills.list`
- `codex.discovery.apps.list`
- `codex.discovery.plugins.list`
- `codex.discovery.plugins.read`

Use these methods before constructing rich input:

- `skills.list` returns stable `skill.path` values
- `apps.list` returns stable `mention_path=app://<id>` values
- `plugins.list` and `plugins.read` return stable `mention_path=plugin://<plugin>@<marketplace>` values

Result-shape guidance:

- use the normalized stable fields declared in Agent Card / OpenAPI first
- inspect `codex.raw` only when you need upstream-specific fields outside the declared minimum contract
- `plugin/list` and `plugin/read` remain upstream experimental; this service exposes a stable minimum subset plus passthrough raw payloads

### Skills List (`codex.discovery.skills.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 11,
    "method": "codex.discovery.skills.list",
    "params": {
      "cwds": ["/workspace/project"],
      "forceReload": true
    }
  }'
```

### Apps List (`codex.discovery.apps.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 12,
    "method": "codex.discovery.apps.list",
    "params": {
      "limit": 20,
      "forceRefetch": false
    }
  }'
```

### Plugins List (`codex.discovery.plugins.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 13,
    "method": "codex.discovery.plugins.list",
    "params": {
      "cwds": ["/workspace/project"],
      "forceRemoteSync": false
    }
  }'
```

### Plugin Read (`codex.discovery.plugins.read`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 14,
    "method": "codex.discovery.plugins.read",
    "params": {
      "marketplacePath": "/workspace/project/.codex/plugins/marketplace.json",
      "pluginName": "sample"
    }
  }'
```

### Discovery Watch (`codex.discovery.watch`)

Upstream Codex emits `skills/changed` and `app/list/updated` as server-side notifications. This service does not expose a standalone server-push JSON-RPC transport, so it bridges those signals through a background A2A task stream.

- start a watch with `codex.discovery.watch`
- subscribe or re-subscribe through `tasks/resubscribe`
- consume `DataPart` payloads with:
  - `kind=skills_changed`
  - `kind=apps_updated`

Watch start example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 15,
    "method": "codex.discovery.watch",
    "params": {
      "request": {
        "events": ["skills.changed", "apps.updated"]
      }
    }
  }'
```

The JSON-RPC result returns `task_id` and `context_id`. Then use the standard task stream:

```bash
curl -sS http://127.0.0.1:8000/v1/tasks/<task_id>:subscribe \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}"
```

## Codex Thread Lifecycle (A2A Extension)

This service exposes provider-private thread lifecycle methods through JSON-RPC:

- `codex.threads.fork`
- `codex.threads.archive`
- `codex.threads.unarchive`
- `codex.threads.metadata.update`
- `codex.threads.watch`
- `codex.threads.watch.release`

Lifecycle control guidance:

- treat `codex.threads.*` as a lifecycle management surface separate from `codex.sessions.*` query/control methods
- control methods return a stable minimum thread summary: `id`, `title`, optional `status`, and `codex.raw`
- release watch ownership with `codex.threads.watch.release` using the `task_id` returned by `codex.threads.watch`
- `thread/unsubscribe` is intentionally not part of this first-stage stable contract because upstream unsubscribe is connection-scoped

### Thread Fork (`codex.threads.fork`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 16,
    "method": "codex.threads.fork",
    "params": {
      "thread_id": "thr-1",
      "request": {
        "ephemeral": true
      }
    }
  }'
```

### Thread Archive (`codex.threads.archive`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 17,
    "method": "codex.threads.archive",
    "params": {
      "thread_id": "thr-1"
    }
  }'
```

### Thread Unarchive (`codex.threads.unarchive`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 18,
    "method": "codex.threads.unarchive",
    "params": {
      "thread_id": "thr-1"
    }
  }'
```

### Thread Metadata Update (`codex.threads.metadata.update`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 19,
    "method": "codex.threads.metadata.update",
    "params": {
      "thread_id": "thr-1",
      "request": {
        "gitInfo": {
          "branch": "feature/thread-lifecycle",
          "originUrl": "https://github.com/example/repo.git"
        }
      }
    }
  }'
```

### Thread Watch (`codex.threads.watch`)

Upstream Codex emits `thread/started`, `thread/status/changed`, `thread/archived`, `thread/unarchived`, and `thread/closed` as server-side notifications. This service bridges those signals through a background A2A task stream rather than exposing standalone server-push JSON-RPC notifications.

- start a watch with `codex.threads.watch`
- subscribe or re-subscribe through `tasks/resubscribe`
- supported watch event filters are `thread.started`, `thread.status.changed`, `thread.archived`, `thread.unarchived`, and `thread.closed`
- consume `DataPart` payloads with:
  - `kind=thread_started`
  - `kind=thread_status_changed`
  - `kind=thread_archived`
  - `kind=thread_unarchived`
  - `kind=thread_closed`

Watch start example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 20,
    "method": "codex.threads.watch",
    "params": {
      "request": {
        "events": ["thread.started", "thread.status.changed", "thread.archived"],
        "threadIds": ["thr-1"]
      }
    }
  }'
```

The JSON-RPC result returns `task_id` and `context_id`. Then use the standard task stream:

```bash
curl -sS http://127.0.0.1:8000/v1/tasks/<task_id>:subscribe \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}"
```

Watch release example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 21,
    "method": "codex.threads.watch.release",
    "params": {
      "task_id": "<task_id>"
    }
  }'
```

## Codex Interrupt Recovery (A2A Extension)

This service also exposes adapter-local interrupt recovery through JSON-RPC:

- `codex.interrupts.list`

Interrupt-recovery guidance:

- use `codex.interrupts.list` to rediscover active pending interrupt request IDs for the current authenticated caller after reconnecting
- optionally pass `type=permission|question|permissions|elicitation` to narrow results
- recovery results are read-only handles; resolve the interrupt itself through the shared `a2a.interrupt.*` callback methods

### Interrupt Recovery (`codex.interrupts.list`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 20,
    "method": "codex.interrupts.list",
    "params": {
      "type": "permission"
    }
  }'
```

The result returns `items`, where each item includes `request_id`, `interrupt_type`, session/task context, expiry timestamps, and adapter-built interrupt `properties`.

## Codex Turn Control (A2A Extension)

This service exposes provider-private active-turn steering through JSON-RPC:

- `codex.turns.steer`

Turn-control guidance:

- use `codex.turns.steer` only when the target thread already has an active regular turn
- pass `expected_turn_id` so the request fails fast if the active turn changed before the steer request arrived
- `request.parts` accepts the same stable rich input items as `codex.sessions.prompt_async`
- turn-level override fields are intentionally rejected, including `metadata`, `metadata.codex.directory`, `metadata.codex.execution`, and request-level model/agent/system variants

### Turn Steer (`codex.turns.steer`)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 21,
    "method": "codex.turns.steer",
    "params": {
      "thread_id": "thr-1",
      "expected_turn_id": "turn-9",
      "request": {
        "parts": [
          {"type": "text", "text": "Focus on the failing tests first."}
        ]
      }
    }
  }'
```

The result returns a minimal control envelope with `ok`, `thread_id`, and `turn_id`.

## Codex Review Control (A2A Extension)

This service exposes provider-private review-start control through JSON-RPC:

- `codex.review.start`
- `codex.review.watch`

Review-control guidance:

- use `codex.review.start` when you want the upstream reviewer surface rather than a slash command sent through `codex.sessions.command`
- supported target types are `uncommittedChanges`, `baseBranch`, `commit`, and `custom`
- `delivery` supports `inline` and `detached`
- `codex.review.start` remains control-only and returns the review handle (`turn_id`, `review_thread_id`)
- use `codex.review.watch` when you need a stable review watch task bridge over `tasks/resubscribe`

### Review Start (`codex.review.start`)

Inline commit review example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 22,
    "method": "codex.review.start",
    "params": {
      "thread_id": "thr-1",
      "delivery": "inline",
      "target": {
        "type": "commit",
        "sha": "commit-demo-123",
        "title": "Polish tui colors"
      }
    }
  }'
```

Detached review for current uncommitted changes:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 23,
    "method": "codex.review.start",
    "params": {
      "thread_id": "thr-1",
      "delivery": "detached",
      "target": {
        "type": "uncommittedChanges"
      }
    }
  }'
```

The result returns `ok`, `turn_id`, and `review_thread_id`. When `delivery=detached`, `review_thread_id` identifies the detached review thread.

### Review Watch (`codex.review.watch`)

Use the handles returned by `codex.review.start` to start a review watch task:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 24,
    "method": "codex.review.watch",
    "params": {
      "thread_id": "thr-1",
      "review_thread_id": "thr-1-review",
      "turn_id": "turn-review-1",
      "request": {
        "events": [
          "review.started",
          "review.status.changed",
          "review.completed",
          "review.failed"
        ]
      }
    }
  }'
```

`codex.review.watch` returns `ok`, `task_id`, and `context_id`. Consume the lifecycle stream through `tasks/resubscribe`.

Supported review watch events:

- `review.started`
- `review.status.changed`
- `review.completed`
- `review.failed`

The bridge is intentionally coarse-grained:

- `review.started` is emitted locally when the watch task begins
- `review.status.changed` projects upstream `thread/status/changed` updates for the watched review thread
- `review.completed` and `review.failed` project the watched review turn terminal status

## Codex Interrupt Callback (A2A Extension)

When stream metadata reports an interrupt request at `metadata.shared.interrupt`, clients can reply through JSON-RPC extension methods:

- asked lifecycle events expose `phase=asked`
- resolved lifecycle events expose `phase=resolved`
- resolved events may also expose `resolution=replied|rejected`

- `a2a.interrupt.permission.reply`
  - required: `request_id`
  - required: `reply` (`once` / `always` / `reject`)
  - optional: `message`
- `a2a.interrupt.question.reply`
  - required: `request_id`
  - required: `answers` (`Array<Array<string>>`)
- `a2a.interrupt.question.reject`
  - required: `request_id`
- `a2a.interrupt.permissions.reply`
  - required: `request_id`
  - required: `permissions` (`object`, granted subset only)
  - optional: `scope` (`turn` / `session`)
- `a2a.interrupt.elicitation.reply`
  - required: `request_id`
  - required: `action` (`accept` / `decline` / `cancel`)
  - optional: `content`

Permission reply example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "a2a.interrupt.permission.reply",
    "params": {
      "request_id": "<request_id>",
      "reply": "once"
    }
  }'
```

Permissions reply example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "a2a.interrupt.permissions.reply",
    "params": {
      "request_id": "<request_id>",
      "permissions": {
        "fileSystem": {
          "write": ["/workspace/project"]
        }
      },
      "scope": "session"
    }
  }'
```

Elicitation reply example:

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "a2a.interrupt.elicitation.reply",
    "params": {
      "request_id": "<request_id>",
      "action": "accept",
      "content": {
        "workspace_root": "/workspace/project"
      }
    }
  }'
```

## Authentication Example (curl)

```bash
curl -sS http://127.0.0.1:8000/v1/message:send \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "message": {
      "messageId": "msg-1",
      "role": "ROLE_USER",
      "content": [{"text": "Explain what this repository does."}]
    }
  }'
```

## JSON-RPC Send Example (curl)

```bash
curl -sS http://127.0.0.1:8000/ \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${DEMO_BEARER_TOKEN}" \
  -d '{
    "jsonrpc": "2.0",
    "id": 101,
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "msg-1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Explain what this repository does."}]
      }
    }
  }'
```

## Streaming Re-Subscription (`subscribe`)

If an SSE connection drops, use `GET /v1/tasks/{task_id}:subscribe` to re-subscribe while the task is still non-terminal.

Terminal-task note:

- While a task is non-terminal, the stream continues with live updates.
- If the task is already terminal, this service replays one final task snapshot and then closes the stream.
- That replay-once terminal behavior is a service-level contract for this deployment. It is published through the compatibility profile and wire contract so clients do not mistake it for a generic A2A baseline rule.
- If the task store is unavailable while loading subscribe state, the service returns a controlled failure instead of exposing backend exception details.
- In the default SQLite-backed deployment, terminal-task persistence is also database-guarded so late conflicting writes are dropped without relying on a process-local stale snapshot check.

## Development Setup

```bash
uv run pre-commit install
```
