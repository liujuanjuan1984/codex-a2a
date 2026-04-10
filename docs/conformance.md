# External Conformance Experiments

This repository keeps internal regression and external interoperability experiments separate on purpose.

## Scope

- `./scripts/doctor.sh` and `./scripts/validate_baseline.sh` remain the default internal regression entrypoints.
- `./scripts/conformance.sh` is a local/manual experiment entrypoint for official external tooling.
- External conformance output is investigation input, not an automatic merge gate.

## Current Experiment Shape

The default `./scripts/conformance.sh` workflow does the following:

1. Syncs the repository environment unless explicitly skipped.
2. Caches or refreshes the official `a2aproject/a2a-tck` checkout.
3. Starts a local dummy-backed `codex-a2a` runtime unless `CONFORMANCE_SUT_URL` points to an existing SUT.
4. Runs the requested TCK category, defaulting to `mandatory`.
5. Preserves raw logs and machine-readable reports under `run/conformance/<timestamp>/`.

The default local SUT uses the repository test double `DummyChatCodexClient`. That keeps the experiment reproducible without requiring a live Codex upstream.

## Usage

Run the default mandatory experiment:

```bash
bash ./scripts/conformance.sh
```

Run a different TCK category:

```bash
bash ./scripts/conformance.sh capabilities
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
- `metadata.json`: experiment metadata including local repo commit and cached TCK commit

## Interpretation Guidance

When a TCK run fails, inspect the raw report before changing the runtime:

- Some failures may point to real runtime gaps.
- Some failures may come from TCK assumptions that do not match `a2a-sdk==0.3.26`.
- Some failures may come from A2A v0.3 versus v1.0 naming or schema drift.
- Some failures may be local experiment artifacts from the dummy-backed runtime.

The experiment is useful only if those categories stay separate during triage.
Use the authenticated compatibility profile and wire contract `protocol_compatibility` fields as the repository-owned declaration of which protocol lines are supported today, partially supported for compatibility, or reserved for future work.

Record first-pass classifications in [conformance-triage.md](./conformance-triage.md).
