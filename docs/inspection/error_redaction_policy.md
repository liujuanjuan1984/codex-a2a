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
- Interactive exec session failure messages and metadata —
  `codex_a2a.execution.exec_runtime._run_exec_session`.
- A2A tool-call error results —
  `codex_a2a.execution.executor._handle_a2a_call_tool`; the error text is
  embedded in follow-up turns within the same upstream session, which session
  queries can later expose.

## Masking rules

Masked:

- POSIX absolute paths (`/a/b/c`).
- Windows drive paths (`C:\a\b`, `C:/a/b`) and UNC paths (`\\server\share`).
- `file://` URIs that embed a local path (`file:///tmp/x`, `file://C:/tmp/x`).
- Any other slash-prefixed token (for example API route strings such as
  `/tasks/123`) — masking is deliberately conservative; a slash-prefixed
  token is treated as a potential path rather than risk leaking a real one.

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
