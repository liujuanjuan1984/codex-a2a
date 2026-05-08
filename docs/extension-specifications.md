# Extension Specifications

This document is the stable specification index for the shared-contract, provider-private, and machine-readable contract URIs used by `codex-a2a`. It is intentionally a compact URI/spec map, not the main consumer guide. For the phase-1 extension classification and disclosure baseline, see [a2a-extension-baseline.md](./a2a-extension-baseline.md). For runtime behavior, request examples, and operational setup, see [guide.md](./guide.md). For compatibility promises and stability expectations, see [compatibility.md](./compatibility.md).

## Discovery Surface Note

`codex-a2a` now splits Agent Card discovery into two layers:

- Public Agent Card: minimal anonymous discovery for core interfaces and shared A2A extensions
- Authenticated extended card: the canonical machine-readable source for provider-private contracts, deployment-aware examples, and machine-readable compatibility metadata
- OpenAPI metadata: minimal anonymous shared-contract disclosure via `x-a2a-extension-contracts` only

Use the public card for lightweight discovery. Fetch the authenticated extended card when you need provider-private contracts, authenticated skill discovery, compatibility metadata, or deployment-aware examples. Use OpenAPI for anonymous shared-contract hints and transport-adjacent examples only.

Provider-private contract note:

- `codex.*` methods in this repository are adapter-managed provider extensions, not portable A2A baseline capabilities.
- Prefer discovery, stable projections, and low-risk watch/control bridges before exposing stronger runtime or host-execution controls.
- When an upstream behavior is highly runtime-internal or host-shaped, the specification should keep it provider-private and should not force it into fake A2A core object semantics.

Negotiation note:

- `urn:codex-a2a:extension:session-binding:v1` and `urn:codex-a2a:extension:stream-hints:v1` are the only current request-level negotiated extensions in this repository family.
- Provider-private `codex.*` extension URIs and the shared interrupt callback URI are declaration-only contracts. Discover them from the authenticated extended Agent Card (with the interrupt callback also summarized on public anonymous surfaces), then invoke the documented JSON-RPC methods directly; no additional `A2A-Extensions` activation header is required for those methods.
- `wire_contract` and `compatibility_profile` are descriptive metadata contracts, not activatable runtime extensions.

Canonical URI note:

- The `urn:codex-a2a:extension:...` identifiers listed below are the canonical extension URIs for the current repository contract line.
- URI paths do not encode disclosure or auth semantics. Scope, public Agent Card visibility, authenticated extended-card visibility, and negotiation mode define the disclosure and activation boundaries.
- This document is the stable repository-owned specification index for those URIs, but the project does not currently claim "spec hosting at the extension URI" for them.
- The current strategy treats this repository-owned URN namespace as the long-lived canonical identity layer rather than as a temporary bridge to a planned HTTPS migration.
- Any future namespace change should be handled as an explicit compatibility-line decision, not as an indefinitely dual-advertised runtime identity.

## Shared Session Binding v1

URI: `urn:codex-a2a:extension:session-binding:v1`

- Scope: shared A2A request metadata for rebinding to an existing upstream session
- Public Agent Card: capability declaration plus minimal routing metadata for `shared.session.id` only
- Authenticated extended card: full profile, notes, and detailed contract metadata
- OpenAPI: anonymous shared contract payload under `x-a2a-extension-contracts.session_binding`
- Runtime field: `metadata.shared.session.id`

## Shared Stream Hints v1

URI: `urn:codex-a2a:extension:stream-hints:v1`

- Scope: shared canonical metadata for block, usage, interrupt, and session hints
- Public Agent Card: metadata roots plus the minimum discoverability fields for block identity, status source, interrupt lifecycle, session identity, and basic token usage
- Authenticated extended card: full shared stream contract including detailed block payload mappings and extended usage metadata
- OpenAPI: anonymous shared contract payload under `x-a2a-extension-contracts.streaming`
- Runtime fields: `metadata.shared.stream`, `metadata.shared.usage`, `metadata.shared.interrupt`, `metadata.shared.session`

## Codex Session Query v1

URI: `urn:codex-a2a:extension:session-query:v1`

- Scope: provider-private Codex session history and low-risk control methods
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Discovery v1

URI: `urn:codex-a2a:extension:discovery:v1`

- Scope: provider-private skills/apps/plugins discovery methods and discovery watch bridge
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Thread Lifecycle v1

URI: `urn:codex-a2a:extension:thread-lifecycle:v1`

- Scope: provider-private thread lifecycle control and lifecycle watch bridge
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Interrupt Recovery v1

URI: `urn:codex-a2a:extension:interrupt-recovery:v1`

- Scope: provider-private interrupt rediscovery contract for authenticated callers
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Turn Control v1

URI: `urn:codex-a2a:extension:turn-control:v1`

- Scope: provider-private active-turn steering for already-running regular turns
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Review Control v1

URI: `urn:codex-a2a:extension:review-control:v1`

- Scope: provider-private review-start control and review lifecycle watch bridge for uncommitted changes, branches, commits, and custom reviewer instructions
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Codex Exec v1

URI: `urn:codex-a2a:extension:exec-control:v1`

- Scope: provider-private standalone interactive command execution
- Discovery surface: authenticated extended card `capabilities.extensions` plus skill inventory
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## Shared Interactive Interrupt v1

URI: `urn:codex-a2a:extension:interactive-interrupt:v1`

- Scope: shared interrupt callback reply methods
- Discovery surface: public Agent Card, authenticated extended card `capabilities.extensions`, and anonymous OpenAPI `x-a2a-extension-contracts.interrupt_callback`
- Transport: provider-private JSON-RPC methods on `POST /`
- Negotiation: declaration-only; discover first, then invoke the documented methods directly
- Public disclosure: method aliases, supported interrupt event names, shared interrupt metadata field names, and the authentication/request-id scope summary only
- Authenticated disclosure: full JSON-RPC endpoint metadata, method contracts, reply schemas, provider-private metadata, success result fields, errors, and runtime profile
- Note: this URI identifies a shared interrupt callback contract and is published on both anonymous and authenticated discovery surfaces. Anonymous publication does not imply anonymous invocation; callback methods require configured transport authentication and an active pending interrupt `request_id`, with session-owner validation when session binding is available.

## A2A Compatibility Profile v1

URI: `urn:codex-a2a:extension:compatibility-profile:v1`

- Scope: compatibility profile describing core baselines, extension retention, and declared service behaviors
- Discovery surface: authenticated extended card `capabilities.extensions`
- Transport: provider-private machine-readable contract metadata
- Negotiation: not applicable; descriptive metadata only
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces

## A2A Wire Contract v1

URI: `urn:codex-a2a:extension:wire-contract:v1`

- Scope: wire-level contract for supported methods, endpoints, and error semantics
- Discovery surface: authenticated extended card `capabilities.extensions`
- Transport: provider-private machine-readable contract metadata
- Negotiation: not applicable; descriptive metadata only
- Note: this URI remains a stable contract identifier and is published only on authenticated discovery surfaces
