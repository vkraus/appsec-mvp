# Silver table ownership

Silver tables and connectors do not line up one to one. Each table can be fed by multiple connectors. Each connector feeds multiple tables. This page makes the mapping explicit so onboarding a new source becomes a checklist of target tables rather than a discovery exercise.

## Onboarding pattern

- A new SCM platform feeds multiple entity tables and optionally contributes platform integrated findings.
- A new scanner feeds a single finding table and relies on existing SCM connectors for referenced repositories.
- A new enrichment source feeds one reference table.

## Silver table ownership by connector category

| Silver Table | Populated By |
|---|---|
| `silver.applications` | CMDB. DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql); struct `silver_applications` in [`src/platform/schemas.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/schemas.py). |
| `silver.repositories` | SCM. DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql); struct `silver_repositories` in [`schemas.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/schemas.py). MVP shape is narrow (`repository_id`, `full_name`, `default_branch`, `updated_at`); the per-source connector pages describe a wider target (`scm_source` / `org` / `name` / `url` / `archived` / `visibility`) that lands when the github transform is extended. |
| `silver.findings` | all scanner categories — SAST, SCA, secret, DAST — and SCM for platform-integrated code/dependency/secret scanning. Records are discriminated by the `category` column. DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql); struct `silver_findings` in [`schemas.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/schemas.py). |
| `silver.finding_location` | derived alongside `silver.findings` when a finding has location detail richer than the projection that lands on `silver.findings` (e.g. `commit_sha`, `end_line`). |
| `silver.app_repo_mapping` | Platform layer (the [app-repo linker](../app-repo-link.md), which joins `silver.applications.app_code` to `silver.repositories.full_name` via the embedded 5-digit code) and CMDB (the deferred ServiceNow `u_repository_id` / `cmdb_rel_ci` paths). Columns: `(application_id, repository_id, link_source, linked_at)` — `link_source` discriminates between signal sources (`"name_match"` from the linker; reserved `"cmdb_rel_ci"`, `"u_repository_id"` for future writes). **Note on the planned `silver.app_repo` rename:** earlier iterations of the redesign called this table `silver.app_repo` with three deltas vs the current shape — a name change, a `source` discriminator, and range columns (`first_seen_at` / `last_seen_at`) for temporal validity. The discriminator delta is implemented today as `link_source`; the name change and range columns remain backlog items. |
| `silver.waf_events` | WAF (AWS WAF). Event-shape, NOT finding-shape — deliberately separate from `silver.findings`. DDL at [`src/platform/sql/silver_tables.sql`](https://github.com/vkraus/appsec-mvp/blob/main/src/platform/sql/silver_tables.sql); schema `silver_waf_events` declared inline in [`src/connectors/aws_waf/transform.py`](https://github.com/vkraus/appsec-mvp/blob/main/src/connectors/aws_waf/transform.py). |
| `silver.hwm` | every connector. Cross-connector high-water-mark state (`(key, subkey, value, updated_at)`). DDL only — not modeled as a PySpark struct. |
| Out-of-MVP: `silver.teams` | CMDB; SCM |
| Out-of-MVP: `silver.commits`, `silver.pull_requests`, `silver.branch_policies` | SCM |
| Out-of-MVP: `silver.pipeline_runs` | CI/CD; SCM for platform-integrated pipelines |
| Out-of-MVP: `silver.dependencies` | SCA scanner; SCM for dependency-graph APIs |
| Out-of-MVP: `silver.vulnerabilities`, `silver.epss_scores`, `silver.kev_entries` | enrichment connectors (NVD / EPSS / CISA KEV) |
| Out-of-MVP: `silver.finding_cve_mapping`, `silver.dedup_links` | derived in the transformation layer |
