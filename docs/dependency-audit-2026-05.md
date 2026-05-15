# Dependency Audit: Dependabot and `a2a-sdk`

## Scope

This note records a focused review of two questions:

1. Whether the repository's recent Dependabot activity is still running normally.
2. Whether `codex-a2a` is keeping up with the latest upstream `a2a-sdk`, and how that differs from `a2a-client-hub/backend`.

Review date: 2026-05-15.

## Dependabot Status

- The repository keeps a weekly Dependabot configuration for the `uv` ecosystem at the repository root.
- The public GitHub Actions page shows a successful `Dependabot Updates` run on 2026-05-14 for `main`.
- The repository also has successful historical Dependabot-generated pull requests and commits, including prior grouped dependency updates that touched `a2a-sdk`.

Conclusion: the trigger path is active and recent runs are succeeding.

## Current `a2a-sdk` Drift

- Before this branch, `codex-a2a` pinned `a2a-sdk==1.0.2`.
- PyPI now publishes `a2a-sdk==1.0.3`.
- `a2a-client-hub/backend` already pins and locks `a2a-sdk==1.0.3`.
- No public open pull request was visible for an `a2a-sdk` update in `codex-a2a` during this review.

Conclusion: the repository was not fully following the newest upstream `a2a-sdk` release in `main`, even though Dependabot itself appears to be running.

## Root Cause

- The 2026-05-14 Dependabot run detected `a2a-sdk==1.0.3` correctly and generated an internal dependency change for it.
- The grouped `uv-all-updates` run also tried to process `setuptools-scm[toml]` from `[build-system]`.
- Dependabot then dropped the entire grouped update because it reported `Previous version was not provided for: 'setuptools-scm[toml]'`.
- Since `a2a-sdk` was part of the same grouped update, its valid bump was discarded together with the broken build-system entry.

Conclusion: this was a grouped-update failure, not an `a2a-sdk` detection failure.

## Implementation Differences vs `a2a-client-hub/backend`

### `codex-a2a`

- Uses a lightweight `A2AClient` facade around `a2a.client.create_client`.
- Keeps a single lazily created SDK client instance plus a cached agent card.
- Handles request metadata splitting and explicit extension negotiation inside the facade.
- Filters negotiated extensions back out of stream and task payloads before returning them.

This design fits a thin adapter runtime that exposes Codex through A2A while also offering a small embedded outbound client.

### `a2a-client-hub/backend`

- Uses a dedicated adapter layer backed by `ClientFactory` instead of a single thin facade.
- Maintains separate streaming and non-streaming SDK clients.
- Wraps shared HTTP transport ownership so SDK-side close operations do not tear down shared transport state.
- Tracks adapter lifecycle, retirement, transport staleness, and domain-specific upstream error mapping.

This design fits a longer-lived hub/control-plane process that multiplexes many peer interactions and needs stronger lifecycle control.

## Version-Adjacent Dependency Differences

Compared with `codex-a2a`, `a2a-client-hub/backend` also targets a newer surrounding runtime stack:

- Python baseline is `>=3.12` instead of `>=3.11`.
- FastAPI and Uvicorn are pinned to newer minimums.
- Pydantic, `pydantic-settings`, `requests`, and `urllib3` are also newer there.

That means `a2a-client-hub/backend` is not only ahead on `a2a-sdk`; it is also operating in a newer dependency envelope overall.

## Change Applied in This Branch

- Excluded `setuptools` and `setuptools-scm*` from the grouped `uv-all-updates` Dependabot rule so build-system bumps can fall back to standalone pull requests.
- Kept the runtime dependency pin unchanged during this branch so the next Dependabot run can validate the configuration fix by raising the pending `a2a-sdk` update itself.

This isolates the Dependabot fix from any manual dependency bump.

## Comparison With `opencode-a2a-serve`

- `opencode-a2a-serve` currently keeps the same `uv-all-updates` grouping pattern and the same `setuptools-scm[toml]>=8,<10` build requirement.
- Its configuration does not add any special handling for grouped build-system dependencies.
- Based on the static configuration, it has the same failure mode and is not more elegant on this point.

Conclusion: the grouped-update guard added in this branch is the stricter and safer handling.

## Notes

A transient GitHub CLI connectivity failure happened early in the review, but later `gh` access succeeded and the Dependabot run and pull request history were verified directly.
