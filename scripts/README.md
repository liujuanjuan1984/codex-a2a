# scripts

Repository-maintainer scripts live here.

This document only explains the remaining repository-local maintainer scripts.
User-facing runtime entrypoints live in the released `codex-a2a-server` CLI.
If you want the fastest install/start path for the service itself, use the
`uv tool` flow in [README.md](../README.md) instead of anything in this
directory.

## Start Here

- [Project overview](../README.md)
- [Architecture guide](../docs/architecture.md)
- [Usage guide](../docs/guide.md)

## Which Script to Use

- [`scripts/validate_baseline.sh`](./validate_baseline.sh):
  run the default local validation baseline used by contributors and CI.
- [`scripts/validate_runtime_matrix.sh`](./validate_runtime_matrix.sh):
  run the reduced runtime-only validation used by the multi-version CI matrix.
- [`scripts/smoke_test_built_cli.sh`](./smoke_test_built_cli.sh):
  validate that a built wheel can be installed through `uv tool` and becomes
  healthy.
- [`scripts/sync_codex_docs.sh`](./sync_codex_docs.sh):
  refresh local upstream Codex reference snapshots when maintainers need them.

## Notes

- End-user runtime startup does not use repository scripts. Prefer the
  published CLI command documented in [README.md](../README.md) and
  [docs/guide.md](../docs/guide.md).
- Keep long-form documentation changes in `docs/` to avoid divergence.
