# Release Integrity Policy

## Decision

Every GitHub Release must ship a `SHA256SUMS` checksum manifest alongside the
wheel and sdist artifacts so consumers can verify artifact integrity
independently of the registry.

## Generation

`scripts/publish_github_release.sh` regenerates `dist/SHA256SUMS` from the
release assets at publish time, before upload:

- One line per asset in `sha256sum` format: `<sha256-hex>  <basename>`.
- Lines are sorted by basename so the manifest is deterministic.
- The manifest itself is uploaded as a release asset and is skipped
  idempotently when it is already present on the release.

## Verification

Consumers verify a downloaded release with:

```bash
sha256sum -c SHA256SUMS
```

## Scope notes

Supply-chain dependency auditing is already covered separately by Dependabot
and `pip-audit` (part of the baseline validation); this policy covers only the
published artifact integrity gap from [#346].

[#346]: https://github.com/liujuanjuan1984/codex-a2a/issues/346
