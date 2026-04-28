# External Conformance Triage

This document is the standing triage template for local `./scripts/conformance.sh` runs against the official `a2aproject/a2a-tck`.

## Standards Used For Triage

- `a2a-sdk==1.0.2` as installed in this repository.
- The default A2A protocol version advertised by this repository: `1.0.0`.
- Repository compatibility policy:
  - machine-readable Agent Card and OpenAPI contracts must reflect implemented runtime behavior;
  - external TCK results are investigation input rather than default merge gates;
  - unsupported behavior should be tracked as implementation work, not silently declared as supported.

## Classification Labels

- `Runtime issue`: the failure reproduces against the repository's declared runtime behavior and should be fixed here.
- `TCK mismatch`: the failure appears to conflict with the installed SDK line or this repository's declared `1.0` baseline.
- `Protocol gap`: the failure identifies work needed to complete the repository's declared `1.0` surface.
- `Local experiment artifact`: the failure comes from the dummy-backed SUT, local auth, local URLs, timing, or other experiment setup details.
- `Needs repro`: the failure needs a focused local probe before assigning ownership.

## Triage Workflow

For each failed or errored node ID:

1. Copy the node ID from `failed-tests.json`.
2. Inspect the corresponding raw details in `pytest-report.json` and `tck.log`.
3. Compare the expectation with `docs/compatibility.md`, authenticated extended card skills/examples, and OpenAPI `x-a2a-extension-contracts` plus `x-codex-contracts`.
4. Assign one classification label.
5. Record whether the next action belongs in this repository, the TCK, or a future protocol compatibility issue.

## Per-Test Triage

Add dated entries below after a real run:

```text
YYYY-MM-DD:
- <nodeid>: <classification>. <short rationale>. Next action: <repo/TCK/future/none>.
```

## Summary

Keep the summary short and separate:

- Count clean runtime issues.
- Count TCK mismatches.
- Count protocol gaps.
- Count local experiment artifacts.
- List follow-up issue numbers when created.
