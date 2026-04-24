# Secrets connectors

Secrets connectors ingest credential-leak detections from pipelines and repository history.

## Capability surface

Secret-detection sources differ from other scanner categories in that severity is rarely a first-class output: a single detection carries at most a confidence or verification flag. The specification maps every secret finding to `severity=high` by default; a per-deployment override is permitted for low-entropy detector classes.

The dominant deployment style is CLI-based, collected from CI/CD pipeline artifacts. Such tooling has no incremental hook and **SHALL** be treated under the full-reload strategy. The natural identification key for a secret finding is the tuple `(repository_id, commit_sha, secret_type, file_path)`; this key is used for deduplication in the canonical Silver Finding pattern. Where the source supports live credential verification, the verification outcome populates the canonical `validity_status` field in Silver.

Secret detection is almost exclusively CI/CD-step in practice: every commit is a potential leak, so per-commit scanning is the operative pattern and the commit SHA is the incremental key. A subset of platforms (GitHub Secret Scanning on the host side) also runs periodic-global scans across repository history to catch historical leaks; connectors should label both outputs with `(repository_id, commit_sha)` so Bronze-to-Silver deduplication unifies the two sources without double-counting.

## Canonical mapping contribution

Secret connectors populate the Silver `finding` table with secrets dedup key `(repository_id, commit_sha, secret_type, file_path)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Three category-specialized skills cover the connector lifecycle for Secrets sources: `analyze-source-secrets`, `generate-connector-secrets`, `validate-implementation-secrets`. See [Skills](skills.md) for the current unspecialized baselines.

## Connectors in this category

- [TruffleHog](trufflehog.md) — intended integration (no MVP implementation).
