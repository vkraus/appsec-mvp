# Requirement Catalog and Traceability

The implementation's test suite binds to requirement identifiers through `@pytest.mark.requirement(...)` markers in the co-located [`src/{platform,connectors/<source>}/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src) folders. The catalog below is the authoritative set; the traceability matrix tracks per-source coverage.

## Schemas and tables

Unity Catalog layout under each per-environment catalog (`appsec_dev`, `appsec_staging`, `appsec_prod`):

| Schema | Owner | Tables / objects |
|---|---|---|
| `silver` | platform | `findings`, `hwm`, `repositories`, `app_repo` (DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql)) |
| `bronze_<source>` | per connector | raw landed records, one schema per connector (`bronze_github`, `bronze_servicenow`, `bronze_sonarqube`, `bronze_semgrep`, `bronze_owasp_zap`) |
| `silver_<source>` | per connector | per-source projection schemas where applicable (`silver_github`, `silver_servicenow`) |
| `gold` | analytics | cross-source aggregations (placeholder; full analytics implementation is future work) |

The cross-source `silver` schema contains the canonical entities and findings every connector reads or writes. `silver.repositories` is populated by SCM connectors (the SCM-first data dependency); `silver.app_repo` is populated by the CMDB connector. Both table shapes live at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql) and are applied by the `platform-bootstrap` job described at [Platform bootstrap job](../platform-bootstrap-job.md).

## Requirement catalog

Each `REQ-*` identifier is bound to pytest markers in the reference implementation.

| ID | Origin | Requirement |
|---|---|---|
| `REQ-ING-AUTH` | Connector abstraction | Connector authentication resolves credentials from the platform secret scope; invalid or expired tokens produce clear error messages rather than silent failures. |
| `REQ-ING-PAG` | Connector abstraction | Pagination traversal completes without data loss or duplication across at least two pages. |
| `REQ-ING-RL` | Connector abstraction | HTTP 429 handling follows the configured retry policy with exponential backoff. |
| `REQ-ING-HWM` | Connector abstraction | High-water-mark resume across two consecutive runs with a mid-run data change fetches only new or changed records on the second run. |
| `REQ-TRF-MAP` | Transformation patterns | Schema mapping holds for every ingested endpoint: Silver columns have correct types, values, and null handling. |
| `REQ-TRF-SEV` | [Canonical normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Severity normalization covers every source-specific severity value, including edge cases; undocumented values fall through to the configured default with a data-quality warning. |
| `REQ-TRF-STS` | [Canonical normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Status normalization covers every source-specific lifecycle state. |
| `REQ-TRF-TS` | [Canonical normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Timestamp normalization covers every source-specific format and emits UTC datetime. |
| `REQ-DQ` | Transformation patterns | At least one Lakeflow Declarative Pipelines expectation per target Silver table; for each expectation, a violating record is quarantined and a valid record passes through. |
| `REQ-DEDUP` | [Silver Finding mapping](canonical-mapping.md#silver-finding-mapping-requirements) | Deduplication creates the correct `dedup_links` records for every applicable tool-overlap pair; similar but distinct findings are not linked. |

## Per-source traceability matrix

Rows are `REQ-*` IDs; columns are the nine selected sources spanning static testing, dynamic testing, and runtime security tiers. Cells are populated by the `validate-implementation` skill when it runs against each source. `PASS` means the bound test passed; `N/A` means the requirement does not apply to the source — either because the category does not exercise the requirement (e.g. CMDB sources emit no findings, so severity/status/dedup do not apply) or because the source is documented but not built in the MVP.

| REQ | ServiceNow | GitHub | GitLab | SonarQube | Semgrep | Dep-Track | TruffleHog | ZAP | AWS WAF |
|---|---|---|---|---|---|---|---|---|---|
| `REQ-ING-AUTH` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | N/A | N/A |
| `REQ-ING-PAG` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | N/A | N/A |
| `REQ-ING-RL` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | N/A | N/A |
| `REQ-ING-HWM` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-TRF-MAP` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-TRF-SEV` | N/A | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-TRF-STS` | N/A | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-TRF-TS` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-DQ` | PASS | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |
| `REQ-DEDUP` | N/A | PASS | N/A | PASS | PASS | N/A | N/A | PASS | N/A |

Cells marked `N/A` indicate a REQ-ID that does not apply to a source — either because the category does not exercise the requirement (for example, `REQ-DEDUP` does not apply to the CMDB category, which emits no findings subject to cross-tool deduplication; the CLI-artifact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit) or because the source is documented but not built in the MVP (GitLab, Dependency-Track, TruffleHog, AWS WAF). The per-source Implementation reports linked from each connector page are the authoritative record of which tests were bound to which REQ-ID.

## How traceability is populated

See [Tests → Traceability](../../analytics/tests.md) for the end-to-end flow: `validate-implementation` runs [`src/connectors/{source}/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors), collects `@pytest.mark.requirement("REQ-...")` markers and outcomes, and emits both the fix list and the traceability row for this matrix.
