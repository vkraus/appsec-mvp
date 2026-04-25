# validate-implementation — CMDB reference

Facts the validate-implementation skill needs to populate the Validation table for a CMDB connector. CMDB sources emit entities, not findings, so the test suite asserts entity-shaped contracts only.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog" (keep table rows in catalog order). The traceability matrix's ServiceNow column is the authoritative per-source row for this category.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-TS`
- `REQ-DQ`

Mark `N/A` (the Validation table row reads `N/A` with bound-test cell `—`):

- `REQ-TRF-SEV` — N/A: CMDB sources emit no findings, so severity normalization is not exercised. Quoted from the matrix legend at `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the category does not exercise the requirement (e.g. CMDB sources emit no findings, so severity/status/dedup do not apply)".
- `REQ-TRF-STS` — N/A: same rationale; entities have no lifecycle status.
- `REQ-DEDUP` — N/A: entity dedup is handled by the natural-key column at Bronze-to-Silver upsert; there are no `dedup_links` rows for this category.

## Default severity

N/A. The test suite does NOT include a `test_severity_normalization`; `REQ-TRF-SEV` is N/A for this category. Cited in `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface": "CMDB data has no severity dimension."

## Incremental strategy

Native update-timestamp HWM column (e.g. `sys_updated_on` for ServiceNow) per `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface". The test suite asserts HWM-resume behaviour in a `test_hwm_resume` (or analogous) function bound to `REQ-ING-HWM`.

## Deduplication key

Not applicable. Entity dedup uses the natural-key column at Bronze-to-Silver upsert; no `dedup_links` rows are emitted. The test suite does NOT include a `test_dedup_links` function; `REQ-DEDUP` is N/A.

## Target Silver tables

`silver.applications`, `silver.teams`, `silver.app_repo_mapping` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The test suite asserts schema mapping bound to `REQ-TRF-MAP` covers all three tables (one assertion or one test per table).

## Authentication norms

Basic-auth service account or OAuth 2.0 client-credentials per `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface". The test suite asserts secret-scope resolution (not inline `os.environ`) in `test_auth_secret_resolution` or analogous, bound to `REQ-ING-AUTH`.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. The test suite does not directly assert tool choice — that lives in `ingest.py` — but the auth / pagination / RL / HWM tests indirectly verify the chosen tool's behaviour.

## Quirks

- **N/A rationale appended to summary.** When emitting the post-table summary, include the canonical phrase "marked `N/A` because CMDB sources do not emit findings (no severity, status, or cross-tool deduplication apply)" — matches the wording in the existing baseline at `mkdocs/docs/connectors/cmdb/servicenow.md` § "## Validation".
- **Custom attributes do not change the REQ-ID set.** Schema-on-read at Bronze absorbs `u_*`-style fields additively; custom-attribute coverage falls under `REQ-TRF-MAP`, not a new REQ-ID.
- **Reference fields read as opaque strings.** Foreign-key fields (e.g. `owned_by`) are not resolved at ingest; the test suite asserts opaque-string behaviour under `REQ-TRF-MAP`, not under a separate REQ-ID.
- **Display vs raw values.** Source-side raw-value mode (e.g. `sysparm_display_value=false`) is asserted under `REQ-TRF-MAP` — the schema mapping test verifies stable IDs across locales.
- **High page count.** Offset-based pagination with page sizes in the thousands; the `REQ-ING-PAG` test asserts traversal across at least two pages without loss or duplication, per the catalog requirement text.
