# validate-implementation — Secrets reference

Facts the validate-implementation skill needs to populate the Validation table for a secret-detection connector. Secrets sources emit findings with reduced lifecycle metadata; severity is conventional and status is N/A.

## Contents
- Applicable REQ-IDs
- Default severity
- Incremental strategy
- Deduplication key
- Target Silver tables
- Authentication norms
- Ingestion-tooling preference
- Quirks

## Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The TruffleHog column of the traceability matrix is the documented intended profile (the source is documented but not built in the MVP, so cells currently read `N/A` across the matrix; the MVP-built profile would be the set below).

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV` — degraded: severity is conventional (`high`), not data-driven from a source field
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-HWM` — N/A: full reload only. The secrets capability surface at `mkdocs/docs/connectors/secrets/index.md` § "Capability surface" states "Such tooling has no incremental hook and SHALL be treated under the full-reload strategy." There is no record-level update column to advance.
- `REQ-TRF-STS` — N/A: secret-detection sources do not expose a status / lifecycle vocabulary. No status transitions exist to normalize.

For CLI-based secret scanners (TruffleHog artefacts — the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are also N/A — quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this fuller N/A profile when validating a CLI-only connector.

Note the discrepancy with the task spec's summary table (which lists `HWM` under "applies"): the catalog matrix and the secrets capability surface are authoritative, and both treat full reload as having no record-level HWM. The plan's `REQ-ING-HWM` could be read as the commit-SHA / scan-start-timestamp HWM for full-reload bootstrapping; if the connector encodes a commit-SHA HWM in `config.yml`, bind a test asserting commit-SHA advancement and mark `REQ-ING-HWM` as `PASS`. Otherwise mark it `N/A` with the rationale above.

## Default severity

`high`, conventional. Per `mkdocs/docs/connectors/secrets/index.md` § "Capability surface": "The specification maps every secret finding to `severity=high` by default; a per-deployment override is permitted for low-entropy detector classes." The `REQ-TRF-SEV` test asserts the literal `high` constant in `mapping.yml` (or — when an override lookup is deployed — the override's severity coverage with the documented data-quality warning).

## Incremental strategy

Full reload per `mkdocs/docs/connectors/secrets/index.md` § "Capability surface". The HWM is the commit SHA (CI/CD-step) or scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning). The test suite either binds `REQ-ING-HWM` against commit-SHA advancement or marks it `N/A` per the discussion in Applicable REQ-IDs.

## Deduplication key

`(repository_id, commit_sha, secret_type, file_path)` per `mkdocs/docs/connectors/secrets/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Per-commit and host-side periodic scans both label records with `(repository_id, commit_sha)`; the dedup test verifies unification without double-counting.

## Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test verifies the discriminator literal alongside the secret-specific fields (`secret_type`, `validity_status`).

## Authentication norms

CLI-based (the dominant style): no API auth — access governed by the artefact bucket's IAM policy. Server-based (rare): PAT or API-key. The test suite binds `REQ-ING-AUTH` only when the connector takes the server-based path; CLI-only variants mark it `N/A`.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CLI-based secret scanners are the documented exception per `CLAUDE.md` ("Ingestion tooling preference order") alongside Semgrep Docker. The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

## Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** `REQ-TRF-MAP` asserts that raw secret values are dropped before Bronze-to-Silver — the projection in `mapping.yml` excludes raw fields explicitly. The test fails if a raw field is present in Silver.
- **Verification semantics.** Where the source supports verification, `REQ-TRF-MAP` asserts that `validity_status` is populated from the source's verification flag (e.g. TruffleHog `Verified`). Sources without verification leave the field null.
- **No status transitions.** `REQ-TRF-STS` is N/A; no test is bound. The Silver `status` field is left null (or set to `open` on first emit) — this constant is asserted under `REQ-TRF-MAP`, not under the omitted `REQ-TRF-STS`.
- **CI/CD-step dominance.** The connector's HWM shape is the commit SHA in practice. The test suite reflects that in the `REQ-ING-HWM` (or its absence) per the discussion above.
- **Detector-class severity overrides.** When a per-deployment override at `config/severity/{source}.yml` is deployed, `REQ-TRF-SEV` asserts the override's coverage and the data-quality fallback. The default code path uses the `mapping.yml` literal `high` and asserts that constant.
