# Requirement Catalog and Traceability

The test suite for the implementation binds to requirement identifiers through `@pytest.mark.requirement(...)` markers in the co-located [`src/{platform,connectors/<source>}/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src) folders. The catalog below is the authoritative set. The traceability matrix tracks coverage for each source.

## Schemas and tables

Unity Catalog layout under each catalog for each environment (`appsec_dev`, `appsec_staging`, `appsec_prod`):

| Schema | Owner | Tables / objects |
|---|---|---|
| `silver` | platform | `findings`, `hwm`, `repositories`, `app_repo` (DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql)) |
| `bronze_<source>` | per connector | raw landed records, one schema per connector (`bronze_github`, `bronze_servicenow`, `bronze_sonarqube`, `bronze_semgrep`, `bronze_owasp_zap`) |
| `silver_<source>` | per connector | projection schemas for each source where applicable (`silver_github`, `silver_servicenow`) |
| `gold` | analytics | cross source aggregations (placeholder; full analytics implementation is future work) |

The cross source `silver` schema contains the standardized entities and findings every connector reads or writes. `silver.repositories` is populated by SCM connectors (the SCM first data dependency). `silver.app_repo_mapping` is populated by the platform-layer [app-repo linker](../app-repo-link.md) (and by the deferred CMDB-side `u_repository_id` / `cmdb_rel_ci` paths). Both table structures live at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql) and are applied by the `platform-bootstrap` job described at [Platform bootstrap job](../platform-bootstrap-job.md).

`silver.applications` carries a 5-digit `app_code` column (populated from `cmdb_ci_business_app.u_app_id` by the ServiceNow connector) used as the join key for the [app-repo linker](../app-repo-link.md). `silver.app_repo_mapping` carries a `link_source` discriminator column (`"name_match"` for rows produced by the linker; reserved future values: `"cmdb_rel_ci"`, `"u_repository_id"`) so multiple signals can coexist in the same table without conflict.

## Requirement catalog

Each `REQ-*` identifier is bound to pytest markers in the reference implementation.

| ID | Origin | Requirement |
|---|---|---|
| `REQ-ING-AUTH` | Connector abstraction | Connector authentication resolves credentials from the platform secret scope. Invalid or expired tokens produce clear error messages rather than silent failures. |
| `REQ-ING-PAG` | Connector abstraction | Pagination traversal completes without data loss or duplication across at least two pages. |
| `REQ-ING-RL` | Connector abstraction | HTTP 429 handling follows the configured retry policy with exponential backoff. |
| `REQ-ING-HWM` | Connector abstraction | High water mark resume across two consecutive runs with a mid run data change fetches only new or changed records on the second run. |
| `REQ-TRF-MAP` | Transformation patterns | Schema mapping holds for every ingested endpoint. Silver columns have correct types, values, and null handling. |
| `REQ-TRF-SEV` | [Standardized normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Severity normalization covers every severity value specific to the source, including edge cases. Undocumented values fall through to the configured default with a data quality warning. |
| `REQ-TRF-STS` | [Standardized normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Status normalization covers every lifecycle state specific to the source. |
| `REQ-TRF-TS` | [Standardized normalization](canonical-mapping.md#severity-and-status-normalization-requirements) | Timestamp normalization covers every format specific to the source and emits UTC datetime. |
| `REQ-DQ` | Transformation patterns | At least one Lakeflow Declarative Pipelines expectation per target Silver table. For each expectation, a violating record is quarantined and a valid record passes through. |
| `REQ-DEDUP` | [Silver Finding mapping](canonical-mapping.md#silver-finding-mapping-requirements) | Deduplication creates the correct `dedup_links` records for every applicable tool overlap pair. Similar but distinct findings are not linked. |

## Traceability matrix per source

Rows are `REQ-*` IDs. Columns are the nine selected sources spanning static testing, dynamic testing, and runtime security tiers. Cells are populated by the `validate-implementation` skill when it runs against each source. `PASS` means the bound test passed. `N/A` means the requirement does not apply to the source. `(pending)` means the connector module is in place but the bound test is deferred (transform stub awaiting Future Work implementation).

| REQ | ServiceNow | GitHub | GitLab | SonarQube | Semgrep | Dep-Track | TruffleHog | ZAP | AWS WAF |
|---|---|---|---|---|---|---|---|---|---|
| `REQ-ING-AUTH` | PASS | PASS | PASS | PASS | N/A | PASS | N/A | N/A | PASS |
| `REQ-ING-PAG` | PASS | PASS | PASS | PASS | N/A | PASS | N/A | N/A | N/A |
| `REQ-ING-RL` | PASS | PASS | PASS | PASS | N/A | PASS | N/A | N/A | N/A |
| `REQ-ING-HWM` | PASS | PASS | PASS | PASS | PASS | PASS | N/A | PASS | PASS |
| `REQ-TRF-MAP` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `REQ-TRF-SEV` | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `REQ-TRF-STS` | N/A | PASS | PASS | PASS | PASS | PASS | N/A | PASS | N/A |
| `REQ-TRF-TS` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `REQ-DQ` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `REQ-DEDUP` | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | N/A |

Cells marked `N/A` indicate a REQ-ID that does not apply to a source. The category does not exercise the requirement. For example, `REQ-DEDUP` does not apply to the CMDB category, which emits no findings subject to cross tool deduplication. The CLI artifact ingestion path has no API auth, pagination, or rate limit. Cells marked `(pending)` indicate that the connector module is generated but the transform implementation is deferred (Future Work). The bound test asserts against an empty stub. Some greenfield connector tests are skipped pending live API fixture capture. These are bound to their REQ-IDs via `@pytest.mark.requirement` markers but skip-marked with `pending live fixtures (B follow-up)`. The Implementation reports for each source linked from each connector page are the authoritative record of which tests were bound to which REQ-ID.

## Platform-layer requirement bindings

Some `REQ-*` IDs are bound to tests in `src/platform/tests/` rather than to a single connector — they cover cross-source framework primitives that no single connector "owns". These bindings are not represented in the per-source matrix above; they are listed here for completeness.

| Component | REQ | Status | Test file |
|---|---|---|---|
| App-repo linker | `REQ-TRF-MAP` | PASS | [`src/platform/tests/test_app_repo_link.py`](https://github.com/vkraus/appsec-mvp/tree/main/src/platform/tests/test_app_repo_link.py) — happy-path join, first-match-wins, Spark wrapper shape |
| App-repo linker | `REQ-DQ` | PASS | [`src/platform/tests/test_app_repo_link.py`](https://github.com/vkraus/appsec-mvp/tree/main/src/platform/tests/test_app_repo_link.py) — unmatched-code drop, no-code-in-name drop, null-app_code guard, code-collision rows, empty-input safety |
| Silver schema/DDL contract | (no REQ binding) | PASS | [`src/platform/tests/test_silver_ddl.py`](https://github.com/vkraus/appsec-mvp/tree/main/src/platform/tests/test_silver_ddl.py) — every `silver_*` `StructType` matches its `silver_tables.sql` `CREATE TABLE` block column-for-column |

The linker is a platform-layer transform that joins `silver.applications` and `silver.repositories`; it has no native source of its own and does not exercise the ingestion-side REQ-IDs (`REQ-ING-*`), severity/status normalization (`REQ-TRF-SEV`/`REQ-TRF-STS`), or cross-tool dedup (`REQ-DEDUP`). See [App-repo linker](../app-repo-link.md) for the operator-facing description.

## How traceability is populated

See [Tests → Traceability](../../analytics/tests.md) for the end to end flow. `validate-implementation` runs [`src/connectors/{source}/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors), collects `@pytest.mark.requirement("REQ-...")` markers and outcomes, and emits both the fix list and the traceability row for this matrix.
