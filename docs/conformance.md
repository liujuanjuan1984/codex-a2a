# Optional External TCK Experiment

The A2A TCK is an optional manual investigation tool. It is not a repository compatibility dependency, protocol authority, CI job, or merge gate.

## Scope

- `./scripts/validate_baseline.sh` remains the default internal regression entrypoint.
- `./scripts/conformance.sh` is a local/manual experiment entrypoint for external tooling.
- TCK output is untrusted investigation input and cannot establish or reject protocol compatibility.
- The current TCK embeds an A2A `v1.0.0` specification snapshot while the compatible released protocol has advanced to `v1.0.1`; maintainers must check the released specification directly.
- No repository workflow runs or gates on the TCK.

## Current Experiment Shape

The default `./scripts/conformance.sh` workflow does the following:

1. Syncs the repository environment unless explicitly skipped.
2. Caches or refreshes the official `a2aproject/a2a-tck` checkout.
3. Starts a local dummy-backed `codex-a2a` runtime unless `CONFORMANCE_SUT_URL` points to an existing SUT.
4. Runs the requested TCK category, defaulting to `mandatory`.
5. Preserves raw logs and machine-readable reports under `run/conformance/<timestamp>/`.

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
- `compatibility.json` / `compatibility.html`: current TCK compatibility reports when emitted
- `tck_report.html` / `junitreport.xml`: current TCK pytest reports when emitted
- `metadata.json`: experiment metadata including local repo commit and cached TCK commit

## Interpretation Guidance

When a TCK run fails, inspect the raw report before changing the runtime:

- Some failures may point to real runtime gaps.
- Some failures may reflect an outdated embedded specification or a TCK-specific interpretation. Resolve those disagreements against the latest compatible released A2A specification.
- Some failures may come from TCK assumptions that do not match `a2a-sdk==1.1.2`.
- Some failures may come from older A2A naming or schema expectations that no longer match the repository's `1.0` contract.
- Some failures may be local experiment artifacts from the dummy-backed runtime.

The experiment is useful only if those categories stay separate during triage. Never convert a TCK result directly into a compatibility claim or an implementation change.
Use the authenticated compatibility profile and wire contract `protocol_compatibility` fields as the repository-owned declaration of which protocol lines are supported today.

The separate scheduled Codex workflow installs the latest stable Codex CLI and runs `scripts/smoke_test_live_codex.sh`. It does not invoke the A2A TCK.

Record first-pass classifications in [conformance-triage.md](./conformance-triage.md).
