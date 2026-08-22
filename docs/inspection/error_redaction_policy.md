# Error Redaction Policy

## Decision

Client-visible error text must never expose absolute local filesystem paths.
All error responses that can leave the process are passed through a single
deterministic masker (`codex_a2a.redact.redact_absolute_paths`) before
serialization.

Masked output uses the fixed placeholder `<redacted-path>`.

## Boundaries covered

- JSON-RPC error responses — `codex_a2a.jsonrpc.errors.adapt_jsonrpc_error`
  (message and error metadata, including nested values).
- REST/HTTP error bodies — `codex_a2a.jsonrpc.errors.build_http_error_body`.
- Raw exception fallback in
  `codex_a2a.jsonrpc.application._generate_error_response`.
- Streaming task error messages — `codex_a2a.execution.executor._emit_error`.

## Masking rules

Masked:

- POSIX absolute paths (`/a/b/c`).
- Windows drive paths (`C:\a\b`, `C:/a/b`) and UNC paths (`\\server\share`).
- `file://` URIs that embed a local path (`file:///tmp/x`, `file://C:/tmp/x`).

Preserved:

- Remote URLs (`https://host/path`).
- Relative paths (`a/b`, `./x`, `../y`).
- Ordinary prose without absolute paths.

## Logging policy

Server-side logs intentionally retain full exception context (including
absolute paths) for diagnosability. Logs are produced on the host that owns
the filesystem and are not sent to clients. Any pipeline that ships logs off
the host must apply the same redaction or restrict access before export.

## Verification

Unit coverage lives in `tests/test_redact.py`, with boundary tests in
`tests/execution/test_error_redaction.py` and
`tests/jsonrpc/test_error_redaction.py`. The masker is deterministic and
idempotent.
