# A2A 1.0 Extension Baseline

This document defines the phase-1 baseline for how `codex-a2a` classifies, documents, and publishes A2A 1.0 extensions and extension-like contracts.

Phase 1 is intentionally internal-facing. It does not change the external extension URI strategy yet. The goal is to establish a single source of truth for extension inventory, disclosure surfaces, and negotiation posture before any breaking URI migration or Agent Card expansion.

## Goals

- Define which runtime surfaces are true A2A extensions versus auxiliary machine-readable contracts.
- Define the intended responsibilities of the public Agent Card, authenticated extended Agent Card, and OpenAPI metadata.
- Centralize extension inventory so that Agent Card, OpenAPI, compatibility guidance, and documentation stop drifting independently.
- Preserve current externally visible behavior during phase 1 unless a change is required to remove ambiguity.

## Extension Classes

`codex-a2a` uses three classes during phase 1:

1. Shared A2A extensions

- These are cross-repository conventions layered onto standard A2A requests, responses, or task streams.
- They belong in `capabilities.extensions`.
- They may participate in request-level extension negotiation when the behavior is activation-sensitive.

2. Provider-private extensions

- These are adapter-managed `codex.*` or shared-repo callback contracts that remain specific to this deployment family.
- They are still treated as extensions conceptually, but their public disclosure remains conservative.
- They should be declared through authenticated extended Agent Card `capabilities.extensions`.
- Their detailed contract payloads remain machine-readable through OpenAPI and human-discoverable through authenticated skill inventory.

3. Machine-readable contract metadata

- These describe compatibility posture, wire-level method availability, and service behavior summaries.
- They are not negotiated runtime extensions.
- They should not be modeled as fake chat/task capabilities just to fit the Agent Card surface.

## Disclosure Responsibilities

### Public Agent Card

- Anonymous discovery surface.
- Declares only the minimum shared extension surface needed for safe interoperability.
- Must not be used as a hiding mechanism for real shared extensions.
- Should remain small even after later phases expand authenticated disclosures.

### Authenticated Extended Agent Card

- Authenticated discovery surface with deployment-aware detail.
- Provider-private extensions that are part of the declared contract should appear here through standard `capabilities.extensions`.
- Skills and examples remain additive discovery aids rather than the primary declaration path.

### OpenAPI Metadata

- Full machine-readable contract surface.
- Remains the detailed source for provider-private request/response method contracts, transport notes, and compatibility metadata.
- Should be derived from the same registry as Agent Card declarations whenever possible.

## Negotiation Rules

- Shared request/response extensions are the only extensions treated as negotiated by default in phase 1.
- Shared request/response extensions use request-level `A2A-Extensions` activation only when the request depends on that negotiated behavior.
- Provider-private `codex.*` contracts and shared callback contracts marked `declaration_only` are discovered through the authenticated extended Agent Card and OpenAPI, then used by directly invoking their documented provider-private methods. They do not require a separate `A2A-Extensions` activation header.
- Compatibility and wire-profile documents are not negotiable extensions.

## Inventory Rules

Every extension-like surface tracked by this repository must define at least:

- stable key
- stable URI
- classification
- disclosure surfaces
- negotiation posture
- contract parameter builder source

That inventory must be reusable by:

- Agent Card extension builders
- OpenAPI extension contract builders
- compatibility taxonomy reporting
- extension specification index documentation

## Phase 1 Non-Goals

- No migration from `urn:` to HTTPS extension URI yet.
- No public expansion of provider-private extension declarations.
- No compatibility shim for A2A 0.3 behavior.

## Follow-On Phases

Phase 2 will unify request-level negotiation, disclosure layering, and runtime behavior around the authenticated extension declaration model.

Canonical URI and spec-hosting strategy remain a separate follow-up track after declaration-path convergence.
