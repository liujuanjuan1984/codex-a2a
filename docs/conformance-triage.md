# External TCK Observation Triage

This document is the standing triage template for local `./scripts/conformance.sh` runs against the official `a2aproject/a2a-tck`.

## Authorities and Evidence Used For Triage

- The latest compatible released upstream A2A specification: currently `v1.0.1` for the repository's advertised `1.0` wire line.
- `a2a-sdk==1.1.2` as installed in this repository.
- The default A2A protocol version advertised by this repository: `1.0`.
- The pinned TCK embeds the older `v1.0.0@173695755607e884aa9acf8ce4feed90e32727a1` spec snapshot. Its assertions are evidence to inspect, never protocol authority.
- Repository compatibility policy:
  - machine-readable Agent Card and OpenAPI contracts must reflect implemented runtime behavior;
  - external TCK results are investigation input rather than default merge gates;
  - unsupported behavior should be tracked as implementation work, not silently declared as supported.

## Classification Labels

- `Runtime issue`: the failure reproduces against the repository's declared runtime behavior and should be fixed here.
- `TCK mismatch`: the failure appears to conflict with the latest compatible released A2A specification, including because the TCK embeds an older spec snapshot or carries a test-specific assumption.
- `Protocol gap`: the failure identifies work needed to complete the repository's declared `1.0` surface.
- `Local experiment artifact`: the failure comes from the dummy-backed SUT, local auth, local URLs, timing, or other experiment setup details.
- `Needs repro`: the failure needs a focused local probe before assigning ownership.

The machine-enforced representation of reviewed failures lives in [`a2a-tck-known-failures.json`](./a2a-tck-known-failures.json). Its `failure_category` values are stable comparison labels, while this document retains the human rationale.

## Triage Workflow

For each failed or errored node ID:

1. Copy the node ID from `failed-tests.json`.
2. Inspect the corresponding raw details in `pytest-report.json` and `tck.log`.
3. Compare the expectation first with the latest compatible released A2A specification, then with `docs/compatibility.md`, authenticated extended card skills/examples, and OpenAPI `x-a2a-extension-contracts`.
4. Check whether the TCK's embedded spec snapshot differs for the affected semantics.
5. Assign one classification label.
6. Record whether the next action belongs in this repository, the TCK, or a future protocol compatibility issue.

## Per-Test Triage

Add dated entries below after a real run:

```text
YYYY-MM-DD:
- <nodeid>: <classification>. <short rationale>. Next action: <repo/TCK/future/none>.
```

2026-08-21 (pinned TCK `5996b79f9cefa6fc390980e383e358a66fb9e49e`, jsonrpc transport, `must` level; 8 failed / 61 passed / 166 skipped):

- `test_artifacts.py::TestTextArtifact::test_task_has_text_artifact[jsonrpc]`: Local experiment artifact. The dummy-backed SUT echoes fixed text instead of the TCK-provided content. Next action: none (fixture limitation of the dummy SUT).
- `test_artifacts.py::TestFileArtifact::test_task_has_file_artifact[jsonrpc]`: Local experiment artifact. Dummy SUT returns a text part where the TCK expects a file part. Next action: none.
- `test_artifacts.py::TestFileUrlArtifact::test_task_has_file_url_artifact[jsonrpc]`: Local experiment artifact. Same dummy-SUT limitation. Next action: none.
- `test_artifacts.py::TestDataArtifact::test_task_has_data_artifact[jsonrpc]`: Local experiment artifact. Same dummy-SUT limitation. Next action: none.
- `test_artifacts.py::TestMessageResponse::test_returns_message_with_text_part[jsonrpc]`: Local experiment artifact. The adapter returns a Task for plain send (streaming-first contract); the TCK expects a Message for this case. Next action: none (documented deviation; see `docs/compatibility.md`).
- `test_error_codes.py::TestJsonRpcErrorCodeMappings::test_content_type_not_supported_error[jsonrpc]`: Local experiment artifact. The TCK sends a raw unauthenticated request; the repository's auth wall (by design) returns 401 before the content-type check can produce `ContentTypeNotSupportedError` (-32005). The authenticated path returns -32005 (covered by repository regression tests). Next action: none.
- `test_error_codes.py::TestJsonRpcErrorCodeMappings::test_version_not_supported_error[jsonrpc]`: Local experiment artifact. Same raw unauthenticated call; the authenticated path returns `VersionNotSupportedError` (-32009). Next action: none.
- `test_error_codes.py::TestJsonRpcErrorCodeRange::test_error_code_in_valid_range[SendMessage-bad-version]`: Local experiment artifact. Same raw unauthenticated call; the authenticated path returns -32009, which is in the valid A2A range. Next action: none.

2026-08-24 (same pinned TCK, HTTP+JSON transport, `must` level; 7 failed / 57 passed / 171 skipped):

- The five artifact/message failures are the HTTP+JSON parametrizations of the same dummy-backend limitations classified above.
- `test_http_status.py::TestHttpJsonStatusCodes::test_content_type_not_supported_returns_415`: Local experiment artifact. Static authentication rejects the unauthenticated probe with 401 before protocol content-type validation. Next action: none.
- `test_http_status.py::TestHttpJsonStatusCodes::test_version_not_supported_returns_400`: Local experiment artifact. Static authentication rejects the unauthenticated probe with 401 before version validation. Next action: none.

Both transport result sets are encoded as exact node IDs plus narrow failure-message categories in a historical observation snapshot. The drift check permits these reviewed differences and stops on additions or category changes for human/spec review; it is not a formal conformance claim and cannot establish compatibility with the newer `v1.0.1` release.

Previously failing adapter defects fixed in this pass (verified by the same pinned TCK run and repository regression tests):

- `test_error_handling.py::TestCoreErrorStructure::test_error_has_code_and_message_jsonrpc`: Fixed. The 401 unauthorized body now carries `code`/`message` (A2A error shape).
- `test_requirements.py::test_must_requirement[STREAM-SUB-004-jsonrpc]` and `test_sse_streaming.py::TestSseSubscribeToTask::test_subscribe_nonexistent_task_returns_error`: Fixed. SubscribeToTask for a missing task now returns `TaskNotFoundError` (-32001) instead of -32603.
- `test_task_lifecycle.py::TestMultiTurn::test_reject_mismatching_context[jsonrpc]` (CORE-MULTI-006): Fixed. SendMessage with a mismatching contextId is now rejected.

## Summary

Keep the summary short and separate:

- Count clean runtime issues.
- Count TCK mismatches.
- Count protocol gaps.
- Count local experiment artifacts.
- List follow-up issue numbers when created.
