# validate-implementation — SCA reference

Facts the validate-implementation skill needs to populate the Validation table for an SCA connector. SCA sources emit dependency-keyed findings; the full ten REQ-IDs apply for server-based deployments.

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

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". Server-based SCA (Dependency-Track shape) tracks the same row pattern as SAST.

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

CLI-based SCA (package-manager audit artefacts): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — same rationale as the CLI-artefact SAST path quoted from `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the CLI-artifact ingestion path … has no API auth, pagination, or rate limit." Apply this N/A profile when validating a CLI-only connector.

Platform-integrated SCA (Dependabot in GitHub) inherits the host SCM connector's auth / pagination / rate-limit code; the SCA test suite binds only the transform / DQ / dedup REQ-IDs locally.

## Default severity

`medium` configurable default per `mkdocs/docs/connectors/sca/index.md` § "Capability surface". The test suite asserts severity normalization in `test_severity_normalization`, bound to `REQ-TRF-SEV`, covering the documented source vocabulary (typically `None`, `Low`, `Medium`, `High`, `Critical`; some tools add `UNASSIGNED` or informational levels) and asserting that undocumented values fall through with a data-quality warning per the catalog requirement text.

## Incremental strategy

Per `mkdocs/docs/connectors/sca/index.md` § "Capability surface": server-based uses paginated REST APIs with update-timestamp HWM columns; CLI-based uses commit SHA or scan-start timestamp under full reload; platform-integrated inherits the SCM platform's hook. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the connector's chosen mode.

## Deduplication key

`(repository_id, package_name, cve_id)` per `mkdocs/docs/connectors/sca/index.md` § "Canonical mapping contribution". The test suite asserts `dedup_links` linkage in `test_dedup_links`, bound to `REQ-DEDUP`, against this exact tuple.

## Target Silver tables

`silver.findings` discriminated by `category="sca"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. SCA does NOT write to `silver.dependencies` (that table is fed by SBOM enrichment paths, not the per-finding dedup pipeline); the test suite verifies the connector targets `silver.findings` only under `REQ-TRF-MAP`.

## Authentication norms

PAT or API-key per `mkdocs/docs/connectors/sca/index.md` § "Capability surface". The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`. CLI-based and platform-integrated variants omit or inherit this test as documented above.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. The validation suite verifies pagination and rate-limit behaviour under `REQ-ING-PAG` and `REQ-ING-RL` against whichever tool the connector chose.

## Quirks

- **CVE correlation.** `REQ-TRF-MAP` asserts that the source-supplied advisory linkage is read directly into `cve_id`. Cross-source enrichment (NVD detail, EPSS scoring, KEV flagging) lands at later transform stages and is NOT asserted by the per-connector test suite.
- **SBOM-centric data.** SBOM-driven sources emit per-component records; the connector flattens to per-finding rows. `REQ-TRF-MAP` covers the flattening assertion.
- **PURL availability.** Where the source emits a `purl`, `REQ-TRF-MAP` asserts the field is projected. `package_name`, `package_version`, `ecosystem` are derivable from PURL but the source-side fields are preferred and asserted under the same REQ-ID.
- **Operational pattern axis.** Same CI/CD-step vs periodic-global split as SAST. `REQ-ING-HWM` exercises the chosen mode.
- **Severity scale variation.** Numeric CVSS vs named labels — `REQ-TRF-SEV` asserts coverage over the chosen format with no gaps.
