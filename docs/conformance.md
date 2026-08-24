# External TCK Behavior Probe

This repository keeps internal regression, normative protocol evaluation, and external test-tool observations separate on purpose.

## Scope

- `./scripts/validate_baseline.sh` remains the default internal regression entrypoint.
- `./scripts/conformance.sh` remains separate from the default baseline and runs official external tooling as a non-normative behavior probe.
- The released upstream A2A specification—not the TCK—is authoritative for portable core protocol semantics.
- The pinned TCK currently embeds A2A spec snapshot `v1.0.0@173695755607e884aa9acf8ce4feed90e32727a1`; the latest compatible released protocol is `v1.0.1`, so the tool is already known to lag the normative patch release.
- Mandatory single-transport runs compare against a historical observation snapshot: already-triaged differences may remain, but unexpected changes return nonzero so maintainers inspect them.
- `.github/workflows/compatibility.yml` runs that fixed probe weekly for JSON-RPC and HTTP+JSON, then preserves each transport's evidence as a workflow artifact.
- A green result means only that repository behavior did not drift relative to this exact pinned tool and embedded spec snapshot. It is not evidence of current-spec compatibility or an A2A conformance certificate.

## Current Experiment Shape

The default `./scripts/conformance.sh` workflow does the following:

1. Syncs the repository environment unless explicitly skipped.
2. Caches or refreshes the official `a2aproject/a2a-tck` checkout.
3. Starts a local dummy-backed `codex-a2a` runtime unless `CONFORMANCE_SUT_URL` points to an existing SUT.
4. Runs the requested TCK category, defaulting to `mandatory`.
5. Preserves raw logs and machine-readable reports under `run/conformance/<timestamp>/`.
6. Verifies the TCK commit and its embedded protocol snapshot, then—for mandatory JSON-RPC or HTTP+JSON runs—compares exact failing node IDs, outcomes, and expected failure-message categories with [`a2a-tck-known-failures.json`](./a2a-tck-known-failures.json).

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
- `baseline-comparison.json`: known, resolved, and unexpectedly changed TCK observations for supported mandatory runs
- `compatibility.json` / `compatibility.html`: current TCK compatibility reports when emitted
- `tck_report.html` / `junitreport.xml`: current TCK pytest reports when emitted
- `metadata.json`: experiment metadata including local repo commit, cached TCK commit, and the TCK's embedded protocol release/commit snapshot

## Interpretation Guidance

When a TCK run fails, inspect the raw report before changing the runtime:

- Some failures may point to real runtime gaps.
- Some failures may reflect the TCK's older embedded protocol snapshot or test interpretation; adjudicate them against the latest compatible released A2A specification.
- Some failures may come from TCK assumptions that do not match `a2a-sdk==1.1.2`.
- Some failures may come from older A2A naming or schema expectations that no longer match the repository's `1.0` contract.
- Some failures may be local experiment artifacts from the dummy-backed runtime.

The probe is useful only if those categories stay separate during triage. A new node ID or changed result triggers investigation, not an automatic conclusion that the adapter violated the protocol. The drift check fails when a new node ID appears, an expected `failed`/`error` outcome changes, the failure message no longer matches its reviewed category, the TCK/embedded-spec identity changes, or the raw TCK exit indicates collection, startup, interruption, or another unreported execution failure. A known failure disappearing is reported as resolved only when the raw TCK exit and report agree, and does not fail the run.
Use the authenticated compatibility profile and wire contract `protocol_compatibility` fields as the repository-owned declaration of which protocol lines are supported today.

The same scheduled workflow installs the latest stable Codex CLI and runs `scripts/smoke_test_live_codex.sh`. The smoke check uses an isolated local Responses provider, verifies generated stable and opt-in experimental schema dependencies, discovers/resolves a workspace skill handle, and completes a real stable-API App Server thread/turn without external provider credentials.

## Updating the TCK Observation Snapshot

The observation is pinned to both the TCK commit and its embedded spec snapshot in the JSON file. Updating either is a test-tool migration, not a protocol-baseline update:

1. Compare the proposed TCK's embedded spec snapshot with the latest compatible released upstream A2A specification and list any lag or divergent assumptions.
2. Run both `jsonrpc` and `http-json` against the proposed pinned TCK commit with `CONFORMANCE_BASELINE_MODE=off` and preserve the raw artifacts.
3. Triage every new or changed failure in [conformance-triage.md](./conformance-triage.md). Do not record an unexplained failure as expected.
4. Record the exact TCK/spec identities, pytest node ID, expected outcome, a narrow message regex, and a stable failure category in `a2a-tck-known-failures.json`.
5. Run `scripts/check_tck_regressions.py` against both reports and confirm the observation is unchanged apart from reviewed updates.
6. When a known failure is fixed, remove its snapshot entry after both transports confirm the reduction.

Record first-pass classifications in [conformance-triage.md](./conformance-triage.md).
