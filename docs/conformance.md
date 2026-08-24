# External Conformance Experiments

This repository keeps internal regression and external interoperability experiments separate on purpose.

## Scope

- `./scripts/validate_baseline.sh` remains the default internal regression entrypoint.
- `./scripts/conformance.sh` remains separate from the default baseline and runs official external tooling.
- Mandatory single-transport runs use an incremental known-failure gate: already-triaged differences may remain, but new failures or changed failure categories return nonzero.
- `.github/workflows/compatibility.yml` runs the mandatory TCK weekly against a pinned TCK commit for both JSON-RPC and HTTP+JSON, then preserves each transport's evidence as a workflow artifact.
- A green incremental gate is not an A2A conformance certificate. It means the pinned TCK result did not regress relative to the reviewed repository baseline.

## Current Experiment Shape

The default `./scripts/conformance.sh` workflow does the following:

1. Syncs the repository environment unless explicitly skipped.
2. Caches or refreshes the official `a2aproject/a2a-tck` checkout.
3. Starts a local dummy-backed `codex-a2a` runtime unless `CONFORMANCE_SUT_URL` points to an existing SUT.
4. Runs the requested TCK category, defaulting to `mandatory`.
5. Preserves raw logs and machine-readable reports under `run/conformance/<timestamp>/`.
6. For mandatory JSON-RPC or HTTP+JSON runs, compares exact failing node IDs, outcomes, and expected failure-message categories with [`a2a-tck-known-failures.json`](./a2a-tck-known-failures.json).

The default local SUT uses the repository test double `DummyChatCodexClient`. That keeps the experiment reproducible without requiring a live Codex upstream.
For current TCK releases that do not expose authentication options, the runner loads `scripts/tck_auth_plugin.py` to inject the configured test credential into HTTP transport clients. The SUT authentication middleware remains enabled.

## Usage

Run the default mandatory experiment:

```bash
bash ./scripts/conformance.sh
```

Run a different TCK category:

```bash
bash ./scripts/conformance.sh should
```

Disable baseline comparison for raw investigation:

```bash
CONFORMANCE_BASELINE_MODE=off bash ./scripts/conformance.sh mandatory
```

Target an already running runtime instead of the local dummy-backed SUT:

```bash
CONFORMANCE_SUT_URL=http://127.0.0.1:8000 \
A2A_AUTH_TYPE=bearer \
A2A_AUTH_TOKEN=dev-token \
bash ./scripts/conformance.sh mandatory
```

Skip local environment sync when the repository and cached TCK environment are already current:

```bash
CONFORMANCE_SKIP_REPO_SYNC=1 \
CONFORMANCE_SKIP_TCK_SYNC=1 \
bash ./scripts/conformance.sh mandatory
```

## Artifacts

Each run keeps the following artifacts in the selected output directory:

- `agent-card.json`: fetched public Agent Card
- `health.json`: fetched authenticated health payload when the local SUT is used
- `repo-health.log`: repository environment sync and dependency compatibility output
- `tck.log`: raw TCK console output
- `pytest-report.json`: pytest-json-report output emitted by the TCK runner when available
- `failed-tests.json`: compact list of failed/error node IDs for triage when a report is available
- `baseline-comparison.json`: known, resolved, and regressed failure comparison for supported mandatory runs
- `compatibility.json` / `compatibility.html`: current TCK compatibility reports when emitted
- `tck_report.html` / `junitreport.xml`: current TCK pytest reports when emitted
- `metadata.json`: experiment metadata including local repo commit and cached TCK commit

## Interpretation Guidance

When a TCK run fails, inspect the raw report before changing the runtime:

- Some failures may point to real runtime gaps.
- Some failures may come from TCK assumptions that do not match `a2a-sdk==1.1.2`.
- Some failures may come from older A2A naming or schema expectations that no longer match the repository's `1.0` contract.
- Some failures may be local experiment artifacts from the dummy-backed runtime.

The experiment is useful only if those categories stay separate during triage. The gate fails when a new node ID appears, an expected `failed`/`error` outcome changes, the failure message no longer matches its reviewed category, or the raw TCK exit indicates collection, startup, interruption, or another unreported execution failure. A known failure disappearing is reported as resolved only when the raw TCK exit and report agree, and does not fail the run.
Use the authenticated compatibility profile and wire contract `protocol_compatibility` fields as the repository-owned declaration of which protocol lines are supported today.

The same scheduled workflow installs the latest stable Codex CLI and runs `scripts/smoke_test_live_codex.sh`. The smoke check uses an isolated local Responses provider, verifies generated stable and opt-in experimental schema dependencies, discovers/resolves a workspace skill handle, and completes a real stable-API App Server thread/turn without external provider credentials.

## Updating the Known-Failure Baseline

The baseline is pinned to the TCK commit recorded in the JSON file. Update it only with reviewable evidence:

1. Run both `jsonrpc` and `http-json` against the proposed pinned TCK commit with `CONFORMANCE_BASELINE_MODE=off` and preserve the raw artifacts.
2. Triage every new or changed failure in [conformance-triage.md](./conformance-triage.md). Do not baseline an unexplained failure.
3. Record the exact pytest node ID, expected outcome, a narrow message regex, and a stable failure category in `a2a-tck-known-failures.json`.
4. Run `scripts/check_tck_regressions.py` against both reports and confirm the comparison has no regressions.
5. When a known failure is fixed, remove its baseline entry after both transports confirm the reduction.

Record first-pass classifications in [conformance-triage.md](./conformance-triage.md).
