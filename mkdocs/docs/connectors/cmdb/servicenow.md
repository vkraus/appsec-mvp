# ServiceNow

## What this connector ingests

The ServiceNow connector is the authoritative source for application inventory. It ingests `cmdb_ci_business_app` (business applications), `cmdb_rel_ci` (CI relationships), and optionally `sys_user_group` (owning teams) into Bronze via Lakeflow Connect, then projects to `silver.app_repo_mapping` (application to repository mapping) and `silver_servicenow.applications`. These CMDB objects provide the application to team ownership graph and the application to repository linkage the framework needs to attribute findings to accountable teams.

**Category:** CMDB · **Integration pattern:** Lakeflow Connect (ServiceNow adapter)

Bronze schema: `bronze_servicenow`. Silver projection schema: `silver_servicenow`. Cross source contribution: `silver.app_repo_mapping`.

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, the `silver` schema, and the `servicenow` UC connection (deployed by `bundle deploy` from `src/connectors/servicenow/resources/connection.yml`) must exist. See [Setup platform](../../platform/index.md) if Phase 1 is not yet complete.
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** The CMDB connector populates `silver.app_repo_mapping` with `(application_id, repository_id, linked_at)` rows that reference `silver.repositories.repository_id` populated by SCM. Without an SCM connector running first, the join from `silver.app_repo_mapping` to `silver.repositories` will not resolve and downstream gold layer rollups (e.g. business application rollup) will return empty results.

## User inputs

| Input | Where to obtain | Used as |
|---|---|---|
| ServiceNow instance URL | The tenant for the user. For demos, register a [Personal Developer Instance (PDI)](https://developer.servicenow.com/) and read the URL from the activation email. | Env var `SERVICENOW_URL` consumed by `src/connectors/servicenow/scripts/load-secrets.sh`. Also passed as DAB var `servicenow_host` (without scheme) at `bundle deploy`. |
| ServiceNow service account username | A user granted the `rest_service` and `cmdb_read` roles. | Env var `SERVICENOW_USERNAME`; DAB var `servicenow_username`. |
| ServiceNow service account password | The password for the same user. | Env var `SERVICENOW_PASSWORD`; DAB var `servicenow_password`. |

!!! warning "ServiceNow PDI caveat"
    The user procedure assumes the ServiceNow tenant supports Databricks Lakeflow Connect. PDIs may or may not expose the necessary interfaces. If the pipeline fails to authenticate, fall back to a licensed tenant.

## Optional source runtime

If you want appsec-mvp to seed *demo* CMDB business app records in your tenant (two `cmdb_ci_business_app` records, three `cmdb_ci_appl` records, plus relationship rows in `cmdb_rel_ci`), apply the optional runtime under `src/connectors/servicenow/runtime/`. See [`src/connectors/servicenow/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/servicenow/runtime) for variables and apply notes (the runtime requires `bash`, `curl`, and `jq` on the user PATH).

Users with a populated CMDB skip the runtime. Wire the existing instance URL and credentials directly via the next section.

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/servicenow/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `servicenow_url` | `SERVICENOW_URL` | Instance URL the connector calls. |
| `servicenow_username` | `SERVICENOW_USERNAME` | Service account username. |
| `servicenow_password` | `SERVICENOW_PASSWORD` | Service account password. |

The Lakeflow connection itself reads its values from DAB variables (`servicenow_host`, `servicenow_username`, `servicenow_password`) at deploy time. Loading them into the secret scope as well lets ad hoc connector code (e.g. one off REST calls, debug notebooks) read them via `dbutils.secrets`.

Run from repo root after Phase 1 completes:

```bash
export SERVICENOW_URL="https://devXXXXX.service-now.com"
export SERVICENOW_USERNAME="appsec_mvp_svc"
export SERVICENOW_PASSWORD="..."
bash src/connectors/servicenow/scripts/load-secrets.sh
# OK: servicenow secrets loaded into scope mvp-connectors
```

## Reference

### API

ServiceNow exposes two REST APIs for CMDB data. The Table API (`/api/now/table/{tableName}`) provides generic read and write operations against any table and is the primary interface for `cmdb_ci_business_app` and `sys_user_group` reads. The connector sends `sysparm_fields` to restrict the response to the columns listed in the `cmdb_ci_business_app` consumed fields table below and the corresponding tables for other entities.

The CMDB Instance API (`/api/now/cmdb/instance/{className}`) understands the CI class hierarchy and can return a CI record with its outbound and inbound relationships in a single response. The reference implementation uses it selectively for hierarchical reads (for example, to resolve `cmdb_ci_business_app` instances that extend a custom base class). Flat table reads use the Table API because its query capabilities are richer and its pagination is simpler.

Both APIs require authentication on every request. The connector supports Basic Authentication (service account granted `rest_service` and `cmdb_read` roles) and OAuth 2.0 client credentials flow for deployments that prohibit long lived passwords. Credentials are stored in Databricks Secrets and injected at runtime.

### Pagination and rate limits

The Table API uses offset based pagination. `sysparm_offset` is the zero based page start index. `sysparm_limit` is the page size. The default and maximum `sysparm_limit` on standard instances is 10,000 records. The connector uses this value for bulk backfill and exposes it as a configurable parameter. The total record count is returned in the `X-Total-Count` header when `sysparm_count=true`. The connector reads it on the first page to compute the total page count and detect mid run table mutations.

ServiceNow does not publish a Table API rate limit per client on standard tiers. Throughput is governed by the transaction quota subsystem of the instance, which tracks concurrent sessions and cumulative processing time per 60 second window. Exceeding the quota returns `HTTP 429`. The connector applies exponential backoff with jitter and retries up to the limit configured in the connector job template. Users seeing sustained 429s should review the transaction quota configuration and, if necessary, reduce `sysparm_limit`.

### Incremental hook

The `sys_updated_on` column is present on every ServiceNow table and records the UTC equivalent modification timestamp. The connector uses it as the high water mark for all four CMDB tables. At the end of each run, the maximum observed `sys_updated_on` is persisted to the state table, and the next run issues a `sysparm_query` filter `sys_updated_on>javascript:gs.dateGenerate('{hwm}','start')`.

Time zone: although `sys_updated_on` is stored internally in UTC, the Table API renders it in the display time zone of the calling user unless the profile specifies UTC. The service account for the connector must be set to UTC, or the Bronze to Silver transform must convert using the known offset of the instance. The reference implementation adopts the latter approach to decouple the connector from ServiceNow user profile management.

ServiceNow supports webhook style outbound notifications through Business Rules and Flow Designer, but this is not part of the standard Table API and requires custom application development. The reference implementation does not use it. The webhook preferred rule falls through to the `sys_updated_on` high water mark strategy, which is adequate given that CMDB data changes on a daily rather than sub minute cadence.

### Resource schema excerpt

The fields below are the subset consumed by the connector. Complete schemas are available in the ServiceNow Table API and CMDB Instance API documentation.

*ServiceNow `cmdb_ci_business_app` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key. Stable across updates. |
| `name` | string | Application display name. |
| `short_description` | string | Free text summary. |
| `business_criticality` | reference | Tier (1 to 4 or custom values per instance. See Enumerations section below). |
| `operational_status` | reference | Lifecycle status (see Enumerations section below). |
| `owned_by` | reference (`sys_user_group`) | Owning team reference. Resolved via join to `silver.teams`. |
| `sys_created_on` | datetime | Creation timestamp (normalized to UTC at transform). |
| `sys_updated_on` | datetime | High water mark column (normalized to UTC at transform). |

*ServiceNow `cmdb_rel_ci` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key of the relationship record. |
| `parent` | reference (`cmdb_ci`) | Source CI of the directed relationship. |
| `child` | reference (`cmdb_ci`) | Target CI of the directed relationship. |
| `type` | reference (`cmdb_rel_type`) | Relationship type label, e.g. *Depends on::Used by* or *Hosted on::Hosts*. |
| `sys_created_on` | datetime | Creation timestamp (normalized to UTC at transform). |
| `sys_updated_on` | datetime | High water mark column (normalized to UTC at transform). |

*ServiceNow `sys_user_group` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key. Referenced by `owned_by` in `cmdb_ci_business_app`. |
| `name` | string | Group display name. Becomes `team_name` in `silver.teams`. |
| `manager` | reference (`sys_user`) | Group manager. Provides an escalation contact for security findings. |
| `email` | string | Group contact address. Used as the notification address in gold layer outputs. |
| `parent` | reference (`sys_user_group`) | Parent group. Enables hierarchical team aggregations at the gold layer. |
| `sys_updated_on` | datetime | High water mark column (normalized to UTC at transform). |

### Enumerations

The `business_criticality` field uses integer backed choice values. Default labels are `most_critical` (1), `somewhat_critical` (2), `less_critical` (3), and `not_critical` (4). Production deployments often extend or relabel these. The lookup at `src/connectors/servicenow/severity.yml` must be reviewed per instance before production use.

The `operational_status` field uses a separate integer choice list. Default labels are `operational` (1), `non-operational` (2), `ready` (3), `retired` (6), `pipeline` (7), and `in_maintenance` (8). Values are configurable per instance. `src/connectors/servicenow/status.yml` must be reviewed per deployment. The standard framework vocabulary maps all non-operational and retired values to a single `inactive` status to reduce branching in gold layer computations.

### Quirks

**Custom fields.** Deployments routinely add `u_` prefixed attributes specific to the organization (e.g., `u_data_classification`). The bronze layer absorbs these via schema on read at landing. The raw payload is stored in `_raw_payload` and native columns are added via additive schema evolution, so no connector change is needed. Transformation mappings in `mapping.yml` must be updated only if a custom field is needed in silver or gold.

**Reference field resolution.** Reference fields (`owned_by`, `parent`) return a `sys_id` rather than a resolved sub-object with default parameters. The connector requests raw values via `sysparm_display_value=false` and `sysparm_exclude_reference_link=true`, preserving `sys_id` for silver layer joins. The separate tables plus join strategy in the framework ingests all referenced tables independently. Embedding resolved display names would introduce redundancy.

**Display value versus raw value.** `sysparm_display_value` accepts `false` (raw stored values; connector default), `true` (display strings), and `all` (both, nested). The connector always sets `false` so that reference fields contain stable `sys_id` GUIDs and choice fields contain integer codes. Display strings are locale dependent and change when administrators rename choices.

**Time zone normalization.** `sys_updated_on` and `sys_created_on` are rendered in the display time zone of the calling user. The Bronze to Silver transform applies a `CONVERT_TIMEZONE` cast to UTC using the known offset of the instance, stored as a connector configuration parameter. Users must set this correctly per instance.

## Run the job

The ServiceNow ingestion is a **Lakeflow Connect pipeline** rather than a notebook job. The pipeline is named `servicenow_ingest` (declared in `src/connectors/servicenow/resources/pipeline.yml`) and runs on a daily cron once enabled. Trigger an on demand full refresh:

```bash
databricks bundle run servicenow_ingest --target dev --refresh-all
```

For a one-shot orchestration (load secrets + run + verify counts), use the wrapper:

```bash
bash src/connectors/servicenow/scripts/install.sh
```

Or via the Databricks CLI directly:

```bash
PIPE_ID=$(databricks pipelines list-pipelines --output JSON | jq -r '.[] | select(.name=="servicenow_ingest") | .pipeline_id')
databricks pipelines start --pipeline-id "$PIPE_ID" --full-refresh
```

Wait ~2 minutes. Pipeline status is visible under **Workflows → Lakeflow Pipelines** in the Databricks UI.

**Normalization spot check.**

- Raw ServiceNow `business_criticality = '1 - critical'` becomes silver `criticality = 'critical'`.
- Raw `business_criticality = '2 - high'` becomes silver `criticality = 'high'`.

## Verify

```sql
-- Bronze: raw CMDB rows landed by Lakeflow Connect.
SELECT count(*) FROM appsec_dev.bronze_servicenow.business_applications;
SELECT count(*) FROM appsec_dev.bronze_servicenow.app_cis;

-- Cross-source canonical app↔repo mapping — joins application_id (CMDB) to
-- repository_id (SCM). Schema: src/platform/sql/silver_tables.sql.
SELECT application_id, repository_id, linked_at FROM appsec_dev.silver.app_repo_mapping;

-- Cross-source dependency check — every silver.app_repo_mapping row should
-- join to a silver.repositories row populated by an SCM connector.
SELECT ar.application_id, ar.repository_id, r.full_name
  FROM appsec_dev.silver.app_repo_mapping ar
  LEFT JOIN appsec_dev.silver.repositories r USING (repository_id)
  ORDER BY ar.application_id;
```

For the demo runtime, expect 2 rows in `business_applications` and 3 rows in `app_cis`. Rows in `silver.app_repo_mapping` whose `r.full_name` is `NULL` indicate the SCM connector has not yet ingested the referenced repositories. Install [GitHub](../scm/github.md) (or another SCM) first.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Pipeline stuck on schema inference | Open the connection definition in the Databricks UI (**Catalog → External Data → Connections → servicenow**) and verify the admin user has read access to `cmdb_ci_business_app`. |
| `401 Unauthorized` from the pipeline | Rotate the password in ServiceNow, re-run `bash src/connectors/servicenow/scripts/load-secrets.sh` *and* re-deploy the bundle with the new `--var "servicenow_password=..."` value, then trigger a new pipeline run. |
| 0 rows in bronze after a successful run | PDI may not expose the CMDB tables. Confirm by hitting `https://<host>/api/now/table/cmdb_ci_business_app?sysparm_limit=1` with `curl -u $USER:$PASS`. If the call returns 404, fall back to a licensed tenant. |
| `silver.app_repo_mapping` rows have `repository_id` values not present in `silver.repositories` | Install at least one SCM connector and run it before expecting the cross source join to resolve. See [SCM category](../scm/index.md). |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `src/connectors/servicenow/tests/test_ingest.py::test_auth_secret_resolution` | PASS |
| `REQ-ING-PAG` | `src/connectors/servicenow/tests/test_ingest.py::test_offset_pagination_two_pages` | PASS |
| `REQ-ING-RL` | `src/connectors/servicenow/tests/test_ingest.py::test_429_backoff_retries` | PASS |
| `REQ-ING-HWM` | `src/connectors/servicenow/tests/test_ingest.py::test_sys_updated_on_hwm_resume` | PASS |
| `REQ-TRF-MAP` | `src/connectors/servicenow/tests/test_transform.py::test_business_app_mapping` | PASS |
| `REQ-TRF-SEV` | (none) | N/A |
| `REQ-TRF-STS` | (none) | N/A |
| `REQ-TRF-TS` | `src/connectors/servicenow/tests/test_transform.py::test_sys_updated_on_utc_normalization` | PASS |
| `REQ-DQ` | `src/connectors/servicenow/tests/test_transform.py::test_business_app_expectation_quarantines_null_sys_id` | PASS |
| `REQ-DEDUP` | (none) | N/A |

Collected 7 requirement bound tests via `pytest src/connectors/servicenow/tests/ -v --tb=short` (2026-04-22, 3.4 s wall clock). 7 passed, 3 marked `N/A` because CMDB sources do not emit findings (no severity, status, or cross tool deduplication apply).

### Tests

Tests live under [`src/connectors/servicenow/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/servicenow/tests). The report table above is the outcome per REQ of running the bound tests in that directory.

## Generation log

This connector page was reconciled by the connector lifecycle skills under the retrofit-9-connectors work. The Reference and Validation sections preserve the original implementation grounded prose, and the Generation log table records the actual skill runs that produced the reconciled artefacts.

| Stage              | Skill                              | Inputs                                                                | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (cmdb)            | name=ServiceNow; url=https://docs.servicenow.com/bundle/utah-application-development/page/integrate/inbound-rest/concept/c_TableAPI.html; category=cmdb | mkdocs/docs/connectors/cmdb/servicenow.md §1 to §3                                 | 2026-04-25 | b3af2e0 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (cmdb)        | page hash=41debf8ae0c7                                                | src/connectors/servicenow/, src/connectors/servicenow/tests/, src/connectors/servicenow/severity.yml, src/connectors/servicenow/status.yml, src/connectors/servicenow/resources/job.yml | 2026-04-25 | 8174e57 (retrofit-9-connectors)  |
| Validation         | `validate-implementation` (cmdb)   | module path=src/connectors/servicenow/                                | mkdocs/docs/connectors/cmdb/servicenow.md §5                                       | 2026-04-25 | 2f071b1 (retrofit-9-connectors)          |
