# Extension Specifications

This document is the stable specification index for the extension URIs published by `codex-a2a`. It is intentionally a compact URI/spec map, not the main consumer guide. For runtime behavior, request examples, and operational setup, see [guide.md](./guide.md). For compatibility promises and stability expectations, see [compatibility.md](./compatibility.md).

## Discovery Surface Note

`codex-a2a` now splits Agent Card discovery into two layers:

- Public Agent Card: minimal discovery surface for anonymous capability probing
- Authenticated extended card: detailed deployment-specific contract surface

Use the public card for lightweight discovery. Fetch the authenticated extended card when you need full extension params, compatibility metadata, or provider-private routing details.

## Shared Session Binding v1

URI: `urn:a2a:session-binding/v1`

- Scope: shared A2A request metadata for rebinding to an existing upstream session
- Public Agent Card: capability declaration plus minimal routing metadata
- Authenticated extended card: full profile, notes, and detailed contract metadata
- Runtime field: `metadata.shared.session.id`

## Shared Stream Hints v1

URI: `urn:a2a:stream-hints/v1`

- Scope: shared canonical metadata for block, usage, interrupt, and session hints
- Public Agent Card: metadata roots plus the minimum discoverability fields for block identity, status, interrupt lifecycle, session identity, and basic token usage
- Authenticated extended card: full shared stream contract including detailed block payload mappings and extended usage metadata
- Runtime fields: `metadata.shared.stream`, `metadata.shared.usage`, `metadata.shared.interrupt`, `metadata.shared.session`

## Codex Session Query v1

URI: `urn:codex-a2a:codex-session-query/v1`

- Scope: provider-private Codex session history and low-risk control methods
- Public Agent Card: capability declaration only
- Authenticated extended card: full method matrix, pagination rules, errors, and context semantics
- Transport: A2A JSON-RPC extension methods

## Codex Discovery v1

URI: `urn:codex-a2a:codex-discovery/v1`

- Scope: provider-private skills/apps/plugins discovery methods and discovery watch bridge
- Public Agent Card: capability declaration only
- Authenticated extended card: full method contracts, normalized item fields, and watch-task bridge metadata
- Transport: A2A JSON-RPC extension methods

## Codex Thread Lifecycle v1

URI: `urn:codex-a2a:codex-thread-lifecycle/v1`

- Scope: provider-private thread lifecycle control and lifecycle watch bridge
- Public Agent Card: capability declaration only
- Authenticated extended card: full method contracts, stable thread fields, and watch-task bridge metadata
- Transport: A2A JSON-RPC extension methods

## Codex Turn Control v1

URI: `urn:codex-a2a:codex-turn-control/v1`

- Scope: provider-private active-turn steering for already-running regular turns
- Public Agent Card: capability declaration only
- Authenticated extended card: full method contracts, rejected override fields, and error metadata
- Transport: A2A JSON-RPC extension methods

## Codex Review Control v1

URI: `urn:codex-a2a:codex-review/v1`

- Scope: provider-private review-start control for uncommitted changes, branches, commits, and custom reviewer instructions
- Public Agent Card: capability declaration only
- Authenticated extended card: full target contracts, delivery options, and error metadata
- Transport: A2A JSON-RPC extension methods

## Codex Exec v1

URI: `urn:codex-a2a:codex-exec/v1`

- Scope: provider-private standalone interactive command execution
- Public Agent Card: capability declaration only
- Authenticated extended card: full method contracts, task-stream delivery details, and error metadata
- Transport: A2A JSON-RPC extension methods

## Shared Interactive Interrupt v1

URI: `urn:a2a:interactive-interrupt/v1`

- Scope: shared interrupt callback reply methods
- Public Agent Card: capability declaration, supported interrupt events, and request ID field
- Authenticated extended card: full callback contract, errors, and routing metadata
- Transport: A2A JSON-RPC extension methods

## A2A Compatibility Profile v1

URI: `urn:codex-a2a:compatibility-profile/v1`

- Scope: compatibility profile describing core baselines, extension retention, and declared service behaviors
- Public Agent Card: capability declaration only
- Authenticated extended card: full compatibility profile payload
- Transport: Agent Card extension params and OpenAPI metadata

## A2A Wire Contract v1

URI: `urn:codex-a2a:wire-contract/v1`

- Scope: wire-level contract for supported methods, endpoints, and error semantics
- Public Agent Card: capability declaration only
- Authenticated extended card: full wire contract payload
- Transport: Agent Card extension params and OpenAPI metadata
