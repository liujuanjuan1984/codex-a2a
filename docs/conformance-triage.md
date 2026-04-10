# External Conformance Triage

This document is the standing triage template for local `./scripts/conformance.sh` runs against the official `a2aproject/a2a-tck`.

## Standards Used For Triage

- `a2a-sdk==0.3.26` as installed in this repository.
- The default A2A protocol version advertised by this repository: `0.3.0`.
- Repository compatibility policy:
  - machine-readable Agent Card and OpenAPI contracts must reflect implemented runtime behavior;
  - external TCK results are investigation input rather than default merge gates;
  - unsupported `1.0` behavior should be tracked as future compatibility work, not silently declared as supported.

## Classification Labels

- `Runtime issue`: the failure reproduces against the repository's declared runtime behavior and should be fixed here.
- `TCK mismatch`: the failure appears to conflict with the installed SDK line or this repository's declared v0.3 baseline.
- `Future protocol gap`: the failure is not a v0.3 regression, but it identifies work needed for stronger v1.0 compatibility.
- `Local experiment artifact`: the failure comes from the dummy-backed SUT, local auth, local URLs, timing, or other experiment setup details.
- `Needs repro`: the failure needs a focused local probe before assigning ownership.

## Triage Workflow

For each failed or errored node ID:

1. Copy the node ID from `failed-tests.json`.
2. Inspect the corresponding raw details in `pytest-report.json` and `tck.log`.
3. Compare the expectation with `docs/compatibility.md`, authenticated Agent Card params, and OpenAPI `x-a2a-extension-contracts`.
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
- Count future protocol gaps.
- Count local experiment artifacts.
- List follow-up issue numbers when created.
