# validate-implementation — SCM reference

Facts the validate-implementation skill needs to populate the Validation table for an SCM connector. SCM sources are dual-role: entities (always) plus platform-native findings (where the platform hosts native scanners). All ten REQ-IDs apply.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The GitHub column of the traceability matrix is the authoritative per-source row for this category — every cell is `PASS`.

Apply (all ten — the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`: none.

For pure-entity SCM sources (no platform-native findings consumed), the three finding-only REQ-IDs (`REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`) do not bind to entity-shape tests — but the reference SCM connector (GitHub) consumes platform-native findings (Dependabot, code scanning, secret scanning), so the full ten apply. If validating a pure-entity variant, mark the finding-only REQ-IDs `N/A` with the rationale "pure-entity SCM source; no platform-native findings consumed".

## Default severity

For the finding role: `medium` configurable default per `mkdocs/docs/connectors/scm/index.md` § "Capability surface" (inherits the generic per-tool lookup model). The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering every documented source value (e.g. `low`, `medium`, `high`, `critical` for GitHub code scanning).

For the entity role: N/A — entity rows have no `severity` column.

## Incremental strategy

Three-option preference order per `mkdocs/docs/connectors/scm/index.md` § "Capability surface": webhook → native `updated_at` → full reload. The test suite asserts HWM resume bound to `REQ-ING-HWM` against whichever mode the connector selected; webhook deployments additionally assert the fallback polling window.

## Deduplication key

Per finding shape, per `mkdocs/docs/connectors/scm/index.md`: code-scanning `(repository_id, file_path, rule_id)`; secret-scanning `(repository_id, commit_sha, secret_type, file_path)`; Dependabot `(repository_id, package_name, cve_id)`. The test suite asserts `dedup_links` linkage in `test_dedup_links` per shape, bound to `REQ-DEDUP`. Mis-branching across shapes is itself a `FAIL`.

## Target Silver tables

Authoritative per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies` (also `silver.commits` and `silver.teams` where the source exposes them).
- Finding role: `silver.findings` discriminated by `category` (`sast`, `sca`, `secrets`).

The test suite's `REQ-TRF-MAP` assertions cover both blocks of `mapping.yml` (entities and findings).

## Authentication norms

PAT or OAuth per `mkdocs/docs/connectors/scm/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

## Ingestion-tooling preference

Per the standard order with the practical split documented in the generate-connector SCM reference: Lakeflow Connect for entities; Databricks SDK for findings. The test suite indirectly verifies the chosen tool's pagination and rate-limit behaviour through `REQ-ING-PAG` and `REQ-ING-RL`.

## Quirks

- **Two `mapping.yml` blocks.** Entity and finding blocks are tested separately; `REQ-TRF-MAP` covers both. The dual-shape coverage is mandatory for finding-emitting SCM sources.
- **Plural Silver names are authoritative.** `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. Tests assert against the plural names.
- **Cursor vs keyset pagination.** GraphQL cursor pagination and REST keyset pagination are both exercised by `REQ-ING-PAG` per endpoint; the test suite covers each style the source uses.
- **Webhook replay.** Webhook-mode connectors include a fallback polling-window assertion under `REQ-ING-HWM`.
- **Finding-shape branch.** The `REQ-DEDUP` test exercises every emitted shape (code-scanning, secret-scanning, Dependabot). Mis-branched dedup keys are flagged as `FAIL`.

## sdk-branch validation note

Sources on the `sdk` branch (per `databricks_runtime.ingestion_path == sdk` + `python_sdk_module`) keep `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM` PASS — the framework concerns are still exercised, but via library mocks (e.g. `MagicMock` modeled on PyGitHub's `Github` / `Repository` / `PaginatedList` classes; or python-gitlab's `Gitlab` / `Project` classes) rather than HTTP mocks. No N/A overrides for the `sdk` branch.
