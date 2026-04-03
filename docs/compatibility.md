# Compatibility Guide

This document explains the compatibility promises this repository currently tries to uphold for open-source users, A2A consumers, and coding-agent integrators.

## Runtime Support

- Python versions: 3.11, 3.12, 3.13
- A2A SDK line: `0.3.x`
- A2A protocol version advertised by default: `0.3.0`

The repository pins the SDK version in `pyproject.toml` and validates the published CLI build in CI. Upgrade the SDK deliberately rather than relying on floating dependency resolution.

## Contract Honesty

Machine-readable discovery surfaces must reflect actual runtime behavior:

- public Agent Card
- authenticated extended card
- OpenAPI metadata
- JSON-RPC wire contract
- compatibility profile

If runtime support is not implemented, do not expose it as a supported machine-readable capability.

Open-source consumption guidance:

- Treat the core A2A send / stream / task methods as the portable baseline.
- Treat `urn:a2a:*` entries in this repository as shared repo-family conventions, not as claims that they are part of the A2A core baseline.
- Treat `codex.*` methods plus `metadata.codex.directory` and `metadata.codex.execution` as a Codex-specific control plane layered on top of the portable A2A surface.
- Treat [extension-specifications.md](./extension-specifications.md) as the stable URI/spec index, not as the main usage guide.

## Normative Sources

When documentation or reference material disagrees, treat these as normative in this order:

- runtime behavior validated by tests
- machine-readable discovery output such as Agent Card, authenticated extended card, and OpenAPI metadata
- repository-owned docs in `README.md`, `docs/`, and `CONTRIBUTING.md`

Maintainer-local upstream Codex snapshots generated via `scripts/sync_codex_docs.sh` are optional reference inputs for comparison and protocol context. They do not override this repository's declared service contract.

## Compatibility-Sensitive Surface

This repository still ships as an alpha project. Within that alpha line, these declared surfaces should not drift silently:

- core A2A send / stream / task methods
- shared session-binding metadata
- shared streaming metadata
- declared custom JSON-RPC extension methods
- unsupported-method error shape

Changes to those surfaces should be treated as compatibility-sensitive and should include corresponding test updates.

Service-level behavior layered on top of those core methods should also be declared explicitly when this repository depends on it for interoperability. Current example: terminal `tasks/resubscribe` replay-once behavior is published as a service-level contract, not as a claim about generic A2A runtime semantics.

Task-store resilience is also service-level behavior in this deployment:

- Once a task reaches a terminal state, later conflicting persistence writes are dropped on a first-terminal-state-wins basis.
- In the default SQLite-backed deployment, terminal-task persistence is guarded with an atomic database upsert instead of a process-local read-before-write check.
- Task-store I/O failures are surfaced as stable service errors instead of leaking backend-specific exceptions through request handlers.

Task durability is deployment-dependent:

- `A2A_DATABASE_URL=<sqlalchemy-async-url>` preserves task lookup/cancel/resubscribe state across process restarts.
- `A2A_DATABASE_URL` now defaults to a workspace-local SQLite database at `${CODEX_WORKSPACE_ROOT}/.codex-a2a/codex-a2a.db` when `CODEX_WORKSPACE_ROOT` is configured; otherwise it falls back to `sqlite+aiosqlite:///./codex-a2a.db`. Persistence therefore remains the default runtime behavior.
- The same database-backed mode also preserves session-binding ownership state and pending interrupt callback requests that still fall within their TTL. Session-binding and ownership persistence are independent from the in-memory session cache TTL.
- The default SQLite + WAL profile is intended for a stable local filesystem path, not for network filesystems or sync-managed folders with weaker locking behavior.
- The repository-local migration helper remains intentionally lightweight: it supports additive, adapter-owned schema evolution such as creating tables, adding nullable columns, and writing per-scope schema versions. It should not be read as a promise that heavier schema rewrites will stay in-scope without a tooling change.

## Deployment Profile

The current service profile is intentionally:

- single-tenant
- shared-workspace
- `tenant_isolation=none`

One deployed instance should be treated as a single-tenant trust boundary, not as a secure multi-tenant runtime boundary.

The compatibility surface distinguishes between:

- a stable deployment profile
- runtime features such as directory binding policy, session shell availability, interrupt TTL, and health endpoint exposure

Execution-environment boundary fields are also published through the runtime profile when configured. Those fields are declarative deployment metadata, not promises that every temporary approval, sandbox escalation, or host-side change will be reflected live per request.

## Extension Stability

- Shared metadata and extension contracts should stay synchronized across Agent Card, OpenAPI, and runtime behavior.
- Public Agent Card should stay intentionally minimal. Detailed extension params belong in the authenticated extended card and OpenAPI, not back in the anonymous discovery surface.
- Product-specific extensions should remain stable within the current major line unless explicitly documented otherwise.
- Deployment-conditional methods must be declared as conditional rather than silently disappearing.
- `codex.sessions.shell` is compatibility-sensitive as a one-shot shell snapshot contract. Future interactive exec support must use a separate extension family rather than silently widening this method's behavior.
- Rich input mapping is compatibility-sensitive across both `codex.sessions.prompt_async` and the core A2A message surface. Changes to supported part types, FilePart image handling, or DataPart mention/skill mapping should be treated as wire-level behavior changes.
- `codex.exec.*` is compatibility-sensitive as the standalone interactive exec contract. Changes to handle shapes, task-stream delivery, or lifecycle method names should be treated as wire-level changes.
- `codex.discovery.*` is compatibility-sensitive as the stable discovery contract for `skill.path` and `mention_path` identifiers. Changes to normalized item fields, plugin marketplace mapping, or discovery watch task payload kinds should be treated as wire-level changes.
- `codex.threads.*` is compatibility-sensitive as the provider-private thread lifecycle contract. Changes to lifecycle method names, watch payload kinds, or watch-task bridge event names should be treated as wire-level changes.
- `codex.turns.*` is compatibility-sensitive as the active-turn control contract. Changes to `expected_turn_id` semantics, same-turn rich-input handling, or rejected override fields should be treated as wire-level changes.
- `codex.review.*` is compatibility-sensitive as the review-start control contract. Changes to supported target types, `delivery` semantics, or the absence/presence of a dedicated review watch task bridge should be treated as wire-level changes.
- Provider-private Agent Card skill decomposition is also compatibility-sensitive. Renaming or re-merging `codex.sessions.query/control`, `codex.discovery.query/watch`, `codex.threads.control/watch`, `codex.turns.control`, `codex.review.control`, `codex.exec.control/stream`, or narrowing `codex.interrupt.callback` output modes should be treated as discoverability contract changes.
- Agent Card media modes and `acceptedOutputModes` handling are compatibility-sensitive. Changes to declared default modes, to task-scoped persistence of negotiated modes, or to structured-output downgrade behavior should be treated as wire-level changes.
- For core chat tasks, negotiated output modes are lifecycle-scoped. `message/send`, `message/stream`, `tasks/get`, `tasks/resubscribe`, and push notifications should not drift apart for the same task.
- For core chat requests, explicit `acceptedOutputModes` are also a compatibility-sensitive fail-fast boundary: requests must remain compatible with declared chat output modes, and current chat turns require `text/plain`.

## Extension Taxonomy

This repository distinguishes between three layers:

- core A2A surface
  - standard send / stream / task methods
- shared extensions
  - repo-family conventions such as session binding, stream hints, and interrupt callbacks (`permission`, `question`, `permissions`, and `elicitation` reply surfaces)
- Codex-specific extensions
  - `codex.*` JSON-RPC methods plus `metadata.codex.directory` and `metadata.codex.execution`
  - this now includes:
    - session query/control
    - discovery/query surfaces
    - discovery watch task bridge
    - thread lifecycle watch-task bridge
    - active-turn control
    - review start control
    - standalone interactive exec

Discovery note:

- `codex.discovery.skills.list`, `codex.discovery.apps.list`, `codex.discovery.plugins.list`, and `codex.discovery.plugins.read` are declared read-only discovery methods.
- `codex.discovery.watch` is the declared bridge for upstream `skills/changed` and `app/list/updated` notifications.
- `codex.threads.watch` is the declared thread lifecycle watch-task bridge for upstream `thread/started`, `thread/status/changed`, `thread/archived`, `thread/unarchived`, and `thread/closed` notifications.
- `codex.turns.steer` is the declared active-turn control method for appending additional input to an already-running regular turn.
- `codex.review.start` is the declared review-start control method for `uncommittedChanges`, `baseBranch`, `commit`, and `custom` review targets.
- There is currently no dedicated review watch task bridge. Clients should treat `codex.review.start` as a control-handle surface rather than a separate streaming subscription API.
- `thread/unsubscribe` is intentionally excluded from the stable public contract until this service exposes connection-safe subscription ownership.
- This repository does not claim a generic standalone server-push JSON-RPC transport for those notifications; the compatibility contract is the watch-task bridge published through Agent Card and OpenAPI.

Important note:

- `urn:a2a:*` extension URIs used here should be read as shared conventions in this repository family.
- They are not a claim that those extensions are part of the A2A core baseline.
- `codex.*` methods are intentionally product-specific. They improve Codex-aware workflows but should not be assumed to transfer unchanged to unrelated A2A agents.
- The public Agent Card is intentionally smaller than the authenticated extended card; that size difference is part of the current discovery contract rather than a documentation accident.

## Non-Goals

This repository does not currently promise:

- multi-tenant workspace isolation inside one instance
- OAuth2 runtime token verification
- a generic metrics export protocol such as Prometheus or OpenTelemetry

Those areas may evolve later, but they should not be implied by current machine-readable discovery output.
