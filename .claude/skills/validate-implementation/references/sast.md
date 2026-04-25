# validate-implementation — SAST reference

Facts the validate-implementation skill needs to populate the Validation table for a SAST connector. SAST sources emit code-level findings; the full ten REQ-IDs apply for server-based deployments.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The SonarQube and Semgrep columns of the traceability matrix are the authoritative per-source rows for this category — every cell is `PASS`.

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

Mark `N/A`: none for the server-based deployment style.

CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The same rationale applies to CLI-based SAST. Apply this N/A profile when validating a CLI-only connector.

Platform-integrated SAST (hosted inside the SCM platform): inherits the SCM connector's auth, pagination, and rate-limit code; the SAST test suite binds only the transform / DQ / dedup REQ-IDs locally. The inherited bindings are documented in a comment, not retested.

## Default severity

`medium` configurable default per `mkdocs/docs/connectors/sast/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) and asserting that undocumented values fall through to the configured default with a data-quality warning per the catalog requirement text.

## Incremental strategy

Per `mkdocs/docs/connectors/sast/index.md` § "Capability surface": server-based uses native update-timestamp HWM; CLI-based uses commit SHA or scan-start timestamp under full reload. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against whichever mode the connector selected.

## Deduplication key

`(repository_id, file_path, rule_id)` per `mkdocs/docs/connectors/sast/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple. Mis-keyed `dedup_links` rows are surfaced as `FAIL`.

## Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The test suite's `REQ-TRF-MAP` assertions verify the discriminator literal alongside the field projections.

## Authentication norms

PAT or API-key per `mkdocs/docs/connectors/sast/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based connectors omit this test (the path has no API auth).

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CLI-based SAST is the documented exception per `CLAUDE.md` ("Ingestion tooling preference order"); the validation suite verifies the deviation through the absence of the auth / pagination / RL tests rather than asserting a tool-choice fact directly.

## Quirks

- **Operational pattern axis.** CI/CD-step (commit SHA / run ID) vs periodic-global (updated-since timestamp) modes are exercised by the same `REQ-ING-HWM` test against the connector's chosen mode. The mode is fixed at `config.yml` time, not at test time.
- **CWE category projection.** `REQ-TRF-MAP` asserts that the source's CWE identifier is projected alongside `rule_id`.
- **Severity vocabulary breadth.** `REQ-TRF-SEV` asserts coverage over the FULL documented vocabulary (BLOCKER…INFO, CRITICAL…LOW, or numeric scales). Gaps fail the test.
- **CLI-artefact path.** When the source is CLI-based, the auth / pagination / RL tests are absent (REQ-IDs marked `N/A`); the table summary cites the catalog's "no API auth, pagination, or rate limit" rationale.
- **Rule-pack drift.** `REQ-DEDUP` asserts that `rule_id` is preserved as-is in the dedup key; rule-pack version drift is documented in a transform-level comment, not asserted by the test.
