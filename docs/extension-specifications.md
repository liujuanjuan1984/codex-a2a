# Extension Specifications

This document is the stable specification index for the shared-extension and provider-private contract URIs used by `codex-a2a`. It is intentionally a compact URI/spec map, not the main consumer guide. For runtime behavior, request examples, and operational setup, see [guide.md](./guide.md). For compatibility promises and stability expectations, see [compatibility.md](./compatibility.md).

## Discovery Surface Note

`codex-a2a` now splits Agent Card discovery into two layers:

- Public Agent Card: minimal anonymous discovery for core interfaces and shared A2A extensions
- Authenticated extended card: authenticated skill inventory plus deployment-aware examples for provider-private controls
- OpenAPI metadata: full machine-readable contract payloads via `x-a2a-extension-contracts` and `x-codex-contracts`

Use the public card for lightweight discovery. Fetch the authenticated extended card when you need authenticated skill discovery or deployment-aware examples. Use OpenAPI when you need the full provider-private contract payloads, compatibility metadata, or routing details.

Provider-private contract note:

- `codex.*` methods in this repository are adapter-managed provider extensions, not portable A2A baseline capabilities.
- Prefer discovery, stable projections, and low-risk watch/control bridges before exposing stronger runtime or host-execution controls.
- When an upstream behavior is highly runtime-internal or host-shaped, the specification should keep it provider-private and should not force it into fake A2A core object semantics.

## Shared Session Binding v1

URI: `urn:a2a:session-binding/v1`

- Scope: shared A2A request metadata for rebinding to an existing upstream session
- Public Agent Card: capability declaration plus minimal routing metadata
- Authenticated extended card: full profile, notes, and detailed contract metadata
- OpenAPI: shared contract payload under `x-a2a-extension-contracts.session_binding`
- Runtime field: `metadata.shared.session.id`

## Shared Stream Hints v1

URI: `urn:a2a:stream-hints/v1`

- Scope: shared canonical metadata for block, usage, interrupt, and session hints
- Public Agent Card: metadata roots plus the minimum discoverability fields for block identity, status, interrupt lifecycle, session identity, and basic token usage
- Authenticated extended card: full shared stream contract including detailed block payload mappings and extended usage metadata
- OpenAPI: shared contract payload under `x-a2a-extension-contracts.streaming`
- Runtime fields: `metadata.shared.stream`, `metadata.shared.usage`, `metadata.shared.interrupt`, `metadata.shared.session`

## Codex Session Query v1

URI: `urn:codex-a2a:codex-session-query/v1`

- Scope: provider-private Codex session history and low-risk control methods
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.session_query`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Codex Discovery v1

URI: `urn:codex-a2a:codex-discovery/v1`

- Scope: provider-private skills/apps/plugins discovery methods and discovery watch bridge
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.discovery`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Codex Thread Lifecycle v1

URI: `urn:codex-a2a:codex-thread-lifecycle/v1`

- Scope: provider-private thread lifecycle control and lifecycle watch bridge
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.thread_lifecycle`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Codex Turn Control v1

URI: `urn:codex-a2a:codex-turn-control/v1`

- Scope: provider-private active-turn steering for already-running regular turns
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.turn_control`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Codex Review Control v1

URI: `urn:codex-a2a:codex-review/v1`

- Scope: provider-private review-start control and review lifecycle watch bridge for uncommitted changes, branches, commits, and custom reviewer instructions
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.review_control`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Codex Exec v1

URI: `urn:codex-a2a:codex-exec/v1`

- Scope: provider-private standalone interactive command execution
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.exec_control`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## Shared Interactive Interrupt v1

URI: `urn:a2a:interactive-interrupt/v1`

- Scope: shared interrupt callback reply methods
- Discovery surface: authenticated extended card skill inventory plus OpenAPI `x-codex-contracts.interrupt_callback`
- Transport: provider-private JSON-RPC methods on `POST /codex/jsonrpc`
- Note: this URI identifies a shared repo-family callback contract, but it is not negotiated through `capabilities.extensions`

## A2A Compatibility Profile v1

URI: `urn:codex-a2a:compatibility-profile/v1`

- Scope: compatibility profile describing core baselines, extension retention, and declared service behaviors
- Discovery surface: OpenAPI `x-codex-contracts.compatibility_profile`
- Transport: provider-private machine-readable contract metadata
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`

## A2A Wire Contract v1

URI: `urn:codex-a2a:wire-contract/v1`

- Scope: wire-level contract for supported methods, endpoints, and error semantics
- Discovery surface: OpenAPI `x-codex-contracts.wire_contract`
- Transport: provider-private machine-readable contract metadata
- Note: this URI remains the stable contract identifier but is not published through `capabilities.extensions`
