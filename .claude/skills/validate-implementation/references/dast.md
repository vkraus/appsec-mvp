# validate-implementation — DAST reference

Facts the validate-implementation skill needs to populate the Validation table for a DAST connector. DAST sources emit findings against deployed targets; the HWM is scan-scoped, not record-level. The CLI-artefact ingestion path is the documented N/A profile for the auth / pagination / rate-limit REQ-IDs.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The OWASP ZAP column of the traceability matrix is the authoritative per-source row for this category — `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` read `N/A`; the rest read `PASS`.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS`
- `REQ-TRF-TS`
- `REQ-DQ`
- `REQ-DEDUP`

Mark `N/A`:

- `REQ-ING-AUTH` — N/A: quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit."
- `REQ-ING-PAG` — N/A: same rationale.
- `REQ-ING-RL` — N/A: same rationale.

For server-based DAST consuming a live API (rather than scan-report artefacts), the same N/A profile applies because the connector's incremental work is scan-scoped — there is no API pagination across findings within a scan, and rate limits do not bind on scan-report reads. If a deployment exercises a paginated live-API surface, bind tests for the affected REQ-IDs and mark them `PASS`; otherwise retain the catalog's N/A profile.

## Default severity

`medium` configurable default per `mkdocs/docs/connectors/dast/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented vocabulary (typically `Informational`, `Low`, `Medium`, `High`) and asserting that undocumented values fall through with a data-quality warning per the catalog requirement text.

## Incremental strategy

Scan-id-based, NOT record-level `updated_at`, per `mkdocs/docs/connectors/dast/index.md` § "Capability surface". The connector encodes `hwm_kind: scan_id` (server-based) or `hwm_kind: artefact_prefix` (CI/CD CLI). The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the chosen mode — record-level resume is NOT exercised because the source does not expose it.

## Deduplication key

`(target, alert_id, uri_path)` per `mkdocs/docs/connectors/dast/index.md` § "Canonical mapping contribution" (Silver finding scope `(application_id, target, alert_id)`). The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

## Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve `target` into `application_id`; unmatched targets are NOT dropped (the test asserts they pass through unchanged for inventory-gap analysis, per `mkdocs/docs/connectors/dast/index.md` § "Capability surface": "Unmatched URLs are emitted for inventory-gap analysis.").

## Authentication norms

Style-dependent per `mkdocs/docs/connectors/dast/index.md` § "Capability surface": server-based uses an API key (e.g. `X-ZAP-API-Key` header); CI/CD-step / CLI-artefact has no native auth (object-storage IAM governs access). The test suite omits `REQ-ING-AUTH` for CLI-artefact connectors per the catalog's documented N/A profile.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. DAST scan-report ingestion is typically artefact-driven (autoloader-style on the object-storage prefix) — this is the documented exception. The validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

## Quirks

- **Target vs file.** `REQ-TRF-MAP` asserts the transform-time join against `silver.deployments`. Application linkage at ingest is forbidden; the test fails if an `application_id` is resolved before transform.
- **Inventory-gap analysis.** The `REQ-TRF-MAP` (or a dedicated `REQ-DQ`) test asserts that unmatched targets are emitted unchanged. Filter logic that drops them is a `FAIL`.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. `REQ-DEDUP` asserts that re-emission across scans collapses through the dedup key without double-counting.
- **No record-level `updated_at`.** This is the headline DAST quirk. `REQ-ING-HWM` exercises `scan_id` (or `artefact_prefix`) advancement, NOT a column-based HWM.
- **Scan orchestration vs report collection.** Server-based scan-and-read mode exercises `REQ-ING-HWM` against scan-id advancement plus the orchestration helpers; report-only mode binds the same REQ-ID against the artefact-prefix HWM.
