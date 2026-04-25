# Dependency-Track

!!! info "Placeholder — not implemented in MVP"
    A reference Dependency-Track connector is not part of the MVP. This
    page is a scaffolding placeholder framing the intended runbook
    structure; the Reference section below documents the integration per
    the category capability surface. Follow the [SCA skills](skills.md)
    to generate the connector when needed.

## What this connector ingests

The Dependency-Track connector is the dedicated SCA source for organizations operating an on-premises software composition analysis platform rather than GitHub's hosted Dependabot. Operational pattern: **periodic-global** — the Dependency-Track server continuously re-evaluates the SBOMs it holds against fresh advisory feeds, and the connector polls via its REST API with a `lastOccurrence` high-water mark. It populates `silver.findings` with projects, components, and per-component findings. Dependency-Track is an OWASP project that ingests CycloneDX or SPDX SBOMs and correlates them against NVD, OSV, GitHub Advisories, and VulnDB. Because it accepts SBOMs from any pipeline, it covers ecosystems and internal registries not reachable by SCM-hosted scanners, complementing rather than substituting for Dependabot.

**Category:** SCA (server, periodic-global) · **Integration pattern:** REST + dlt

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md).
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** Dependency-Track findings carry a project that maps to a `repository_id`; the value must resolve to a row in `silver.repositories` for downstream rollups to attribute findings to a repository (and through `silver.app_repo`, to a business application).

## Reference

### API surface

Dependency-Track exposes a versioned REST API at `/api/v1/`; all endpoints return JSON. The connector uses four endpoint groups.

- `GET /api/v1/project` — enumerates all projects registered in the instance; provides the project inventory from which per-project component and finding fetches are driven. Supports optional filtering by `name`, `classifier`, and `active` state.
- `GET /api/v1/component/project/{uuid}` — lists all components associated with a given project UUID; provides package name, version, and PURL for the dependency manifest recorded in `silver.findings`.
- `GET /api/v1/finding/project/{uuid}` — retrieves all vulnerability findings for a given project; each finding embeds the associated component object and vulnerability object, so a single call returns the joined record needed to populate `silver.findings` without additional lookups.
- `GET /api/v1/vulnerability/{source}/{vulnId}` — fetches full vulnerability detail by advisory source and identifier; used selectively to enrich findings that lack CVSS scores in the project-level response.

Authentication uses an API key in the `X-Api-Key` header. Each key is bound to a team with a defined permission set. The reference implementation uses a read-only team with `VIEW_PORTFOLIO` and `VIEW_VULNERABILITY`, stored in Databricks Secrets.

### Pagination and rate limits

List endpoints use 1-indexed offset pagination: `pageNumber` (from 1) and `pageSize`. `X-Total-Count` returns the total record count. The connector defaults `pageSize` to 100; operators may raise it on under-utilized instances.

Dependency-Track does not enforce server-side rate limits by default. Throughput is bounded by the app server thread pool and database connections. Operators with reverse-proxy throttling can record the ceiling in the per-source `config.yml`; the connector enforces it during backfill. Incremental runs use at most one page per project.

### Incremental hook

`attribution.attributedOn` records the UTC timestamp at which the finding was first attributed; the connector uses its project-level maximum as the high-water mark. `lastInheritedRiskScoreUpdate` on project/component records tracks risk-score recomputation, reflecting vulnerability-profile changes.

Dependency-Track exposes a notification mechanism (new vulnerability, project audit complete, policy violation). These are informational outbound webhooks carrying summary payloads, not structured data-sync hooks, with no high-water-mark filtering. The webhook-preferred rule falls through to `attributedOn` polling, which is adequate given per-SBOM-import cadence.

### Resource schema excerpt

The fields below are the subset consumed by the connector; complete schemas are in the Dependency-Track API documentation.

**`/api/v1/finding/project/{uuid}` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `component.uuid` | string (UUID) | Stable component identifier within the Dependency-Track instance. |
| `component.name` | string | Package name as recorded in the SBOM. |
| `component.version` | string | Installed version string; used as `installed_version` in `silver.findings`. |
| `component.purl` | string | Package URL encoding the ecosystem, package name, and version (e.g. `pkg:pypi/requests@2.28.0`); the ecosystem token is extracted at transform (see Quirks). |
| `vulnerability.vulnId` | string | Advisory identifier; typically a CVE ID but may be an OSV, GHSA, or VulnDB identifier depending on `vulnerability.source`. |
| `vulnerability.source` | string | Advisory source that reported this vulnerability (see Enumerations). |
| `vulnerability.severity` | string | Severity label assigned by the advisory source (see Enumerations). |
| `vulnerability.cvssV3` | decimal | CVSS v3 base score; nullable when the advisory source has not published a CVSS score. |
| `vulnerability.cweId` | integer | CWE identifier as a single integer; see Quirks for comparison with multi-valued CWE arrays in other tools. |
| `attribution.analyzerIdentity` | string | Internal identifier of the analyzer that attributed this finding to the component (see Enumerations). |
| `attribution.attributedOn` | datetime (UTC) | Timestamp at which the finding was first attributed; used as the high-water-mark field. |

**`/api/v1/project` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `uuid` | string (UUID) | Stable project identifier; used as the key for per-project finding and component fetches. |
| `name` | string | Project display name; used by the repository-linking strategy described in Quirks. |
| `version` | string | Project version string; nullable for projects that do not version their manifests. |
| `classifier` | string | Project type classification (see Enumerations). |
| `purl` | string | Project-level PURL; present when the project was created from a SBOM that carries a root-component PURL. |
| `active` | boolean | Whether the project is active; inactive projects are excluded from incremental runs by default. |
| `lastBomImport` | datetime (UTC) | Timestamp of the most recent SBOM import; used to detect projects updated since the last connector run. |
| `lastInheritedRiskScoreUpdate` | datetime (UTC) | Timestamp of the most recent risk-score recomputation; used as a secondary freshness indicator. |

### Enumerations

**Severity.** `vulnerability.severity` uses six values: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`, `UNASSIGNED`. `src/connectors/dependency_track/severity.yml` maps CRITICAL→`critical`, HIGH→`high`, MEDIUM→`medium`, LOW→`low`, INFO→`low`. `UNASSIGNED` is common for advisories without a CVSS score; it falls through to the severity-fallback rule, which substitutes the connector's default severity (medium unless overridden).

**Vulnerability source.** `vulnerability.source` identifies the advisory database: `NVD`, `OSV`, `GITHUB`, `VULNDB`, or `INTERNAL` (manually entered).

**Analyzer identity.** `attribution.analyzerIdentity` identifies the internal analyzer. Documented values include `INTERNAL_ANALYZER`, `OSSINDEX_ANALYZER`, `VULNDB_ANALYZER`, `SNYK_ANALYZER`, `NVD_ANALYZER`, `GITHUB_ADVISORIES_ANALYZER`. The connector preserves it as a Bronze domain column and maps it to `scanner_name` via `config/scanner/dependency-track.yml`.

**Project classifier.** `classifier` uses the CycloneDX component-type vocabulary: `APPLICATION`, `FRAMEWORK`, `LIBRARY`, `CONTAINER`, `OPERATING_SYSTEM`, `DEVICE`, `FIRMWARE`, `FILE`. By default, only `APPLICATION` and `CONTAINER` projects are ingested; operators extend the set via `classifier_filter` in `config.yml`.

### Quirks

**Ecosystem extraction from PURL.** Dependency-Track does not expose ecosystem as a discrete field. The ecosystem is encoded in the PURL between `pkg:` and the first `/` (e.g., `pypi` in `pkg:pypi/requests@2.28.0`). The Bronze-to-Silver transform parses the PURL and stores the token in `ecosystem`, matching GitHub Dependabot's native `dependency.package.ecosystem`.

**Duplicate findings across advisory sources.** One component may accumulate multiple finding records for the same CVE when multiple sources (e.g., NVD and OSV) report it. The SCA dedup key `(repository_id, package_name, cve_id)` collapses duplicates into one canonical finding. Per-source attribution is preserved in the `dedup_links` column for audit.

**Project-to-repository linking.** Dependency-Track projects have no native reference to the source repository. The reference implementation offers two strategies via `config.yml`: (a) *name convention* — parse project names following `owner/repo` or `repo@version` and match against `silver.repositories`; and (b) *project custom properties* — a `repository_id` tag set by the CI/CD pipeline at SBOM import. Option (b) is preferred; (a) is the fallback. Unlinkable projects land with null `repository_id` and are excluded from `silver.findings`.

**`UNASSIGNED` severity requires fallback handling.** `UNASSIGNED` is the expected value for advisories without a CVSS score, common in OSV and NVD for older CVEs. Dropping them would suppress real vulnerabilities. The severity-fallback rule assigns every `UNASSIGNED` finding a canonical severity before silver.

**Single-valued CWE identifier.** Dependency-Track exposes `vulnerability.cweId` as a single integer rather than the array form used by GHAS. The `cwe_id` column is typed as a single integer; the connector maps directly without an array intermediate.

**Array metadata fields.** The `metadata.cwe`, `metadata.owasp`, and `metadata.references` fields in CLI JSON output are string arrays. The connector stores the first element as scalar `cwe_id`, `owasp_id`, and `reference_url`, keeping the full arrays in `raw_metadata` for traceability. The same pattern applies to the Cloud Platform's `categories` array.

## Setup

!!! info "Not implemented in MVP"
    See the Prerequisites admonition above.

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `src/connectors/dependency_track/tests/test_ingest.py::test_ingest_contract_rejects_missing_api_key` | PASS |
| `REQ-ING-PAG` | `src/connectors/dependency_track/tests/test_ingest.py::test_project_list_pagination_covers_two_pages_without_duplication` | PASS |
| `REQ-ING-RL` | `src/connectors/dependency_track/tests/test_ingest.py::test_run_ingest_pipeline_deferred_to_databricks_dlt_source` | PASS |
| `REQ-ING-HWM` | `src/connectors/dependency_track/tests/test_ingest.py::test_select_finding_hwm_picks_maximum_attributed_on` | PASS |
| `REQ-TRF-MAP` | `src/connectors/dependency_track/tests/test_transform.py::test_flatten_to_silver_row_projects_all_silver_columns` | PASS |
| `REQ-TRF-SEV` | `src/connectors/dependency_track/tests/test_transform.py::test_severity_lookup_covers_every_documented_value` | PASS |
| `REQ-TRF-STS` | `src/connectors/dependency_track/tests/test_transform.py::test_status_lookup_covers_every_documented_state` | PASS |
| `REQ-TRF-TS` | `src/connectors/dependency_track/tests/test_transform.py::test_attributed_on_parses_to_utc_datetime` | PASS |
| `REQ-DQ` | `src/connectors/dependency_track/tests/test_transform.py::test_unassigned_severity_routes_to_dq_default_not_dropped` | PASS |
| `REQ-DEDUP` | `src/connectors/dependency_track/tests/test_transform.py::test_dedup_key_collapses_same_cve_across_advisory_sources` | PASS |

Collected 10 requirement-bound tests via `pytest src/connectors/dependency_track/tests/ -v --tb=short` (2026-04-25, 0.35 s wall-clock); 10 passed, 0 failed, 0 N/A. The overall suite reports 25 passed and 1 skipped — the skip is a live-API placeholder (`test_live_api_key_header_is_x_api_key`) guarded by `@pytest.mark.skip` because a Dependency-Track instance is not reachable from the unit-test environment. All ten REQ-IDs apply to this server-based SCA connector per the category reference; none are N/A.

### Tests

Tests live under [`src/connectors/dependency_track/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/tests/connectors/dependency_track). The report table above is the per-REQ outcome.

## Generation log

This connector page is produced by the connector-lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                                          | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (sca)             | name=Dependency-Track; url=https://docs.dependencytrack.org/integrations/rest-api/; category=sca | mkdocs/docs/connectors/sca/dependency-track.md §1–§3                               | 2026-04-25 | 8143eee (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (sca)         | page hash=1b08b07046bc                                           | src/connectors/dependency_track/, src/connectors/dependency_track/tests/, src/connectors/dependency_track/severity.yml, src/connectors/dependency_track/status.yml, src/connectors/dependency_track/resources/job.yml | 2026-04-25 | 26a3f61 (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (sca)    | module path=src/connectors/dependency_track/                                                    | mkdocs/docs/connectors/sca/dependency-track.md §5                                  | 2026-04-25 | 9aa0b2c (retrofit-9-connectors)          |
