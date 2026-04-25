# ServiceNow

## Overview

The ServiceNow connector is the authoritative source for application inventory. It populates `silver.applications` from the `cmdb_ci_business_app` CI class, `silver.teams` from `sys_user_group`, and `silver.app_repo_mapping` by resolving relationships in `cmdb_rel_ci`. These CMDB objects provide the application-to-team ownership graph and the application-to-repository linkage the framework needs to attribute findings to accountable teams.

**Category:** CMDB · **Integration pattern:** LakeFlow Connect (ServiceNow adapter)

## Prerequisites

Platform-level prerequisites (AWS, Databricks workspace, Terraform tooling) are covered once in [Platform → Prerequisites](../../platform/prerequisites.md). The ServiceNow-specific handoffs required before `terraform apply` are:

- **ServiceNow tenant.** Register a [Personal Developer Instance (PDI)](https://developer.servicenow.com/) or use a licensed tenant. Capture the instance URL and an admin credential (`servicenow_instance_url`, `servicenow_admin_username`, `servicenow_admin_password` in `terraform.tfvars`).
- **Admin read access** to the CMDB tables consumed by the connector: `cmdb_ci_business_app`, `cmdb_rel_ci`, and `sys_user_group`.
- **Credential scopes.** Basic authentication requires the service account be granted the `rest_service` and `cmdb_read` roles. OAuth 2.0 client-credentials flow is also supported for deployments that prohibit long-lived passwords; credentials are stored in Databricks Secrets (`mvp-connectors` scope, keys `servicenow_url`, `servicenow_username`, `servicenow_password`) and injected at runtime.

!!! warning "ServiceNow PDI caveat"
    The operator procedure assumes the ServiceNow tenant supports Databricks Lakeflow Connect. PDIs may or may not expose the necessary interfaces — if the Lakeflow pipeline fails to authenticate, fall back to a licensed tenant.

## Reference

### API surface

ServiceNow exposes two REST APIs for CMDB data. The Table API (`/api/now/table/{tableName}`) provides generic read and write operations against any table and is the primary interface for `cmdb_ci_business_app` and `sys_user_group` reads. The connector sends `sysparm_fields` to restrict the response to the columns listed in the `cmdb_ci_business_app` consumed fields table below and the corresponding tables for other entities.

The CMDB Instance API (`/api/now/cmdb/instance/{className}`) understands the CI class hierarchy and can return a CI record with its outbound and inbound relationships in a single response. The reference implementation uses it selectively for hierarchical reads (for example, to resolve `cmdb_ci_business_app` instances that extend a custom base class). Flat table reads use the Table API because its query capabilities are richer and its pagination is simpler.

Both APIs require authentication on every request. The connector supports Basic Authentication (service account granted `rest_service` and `cmdb_read` roles) and OAuth 2.0 client-credentials flow for deployments that prohibit long-lived passwords. Credentials are stored in Databricks Secrets and injected at runtime.

### Pagination and rate limits

The Table API uses offset-based pagination: `sysparm_offset` is the zero-based page start index; `sysparm_limit` is the page size. The default and maximum `sysparm_limit` on standard instances is 10,000 records; the connector uses this value for bulk backfill and exposes it as a configurable parameter. The total record count is returned in the `X-Total-Count` header when `sysparm_count=true`; the connector reads it on the first page to compute the total page count and detect mid-run table mutations.

ServiceNow does not publish a per-client Table API rate limit on standard tiers. Throughput is governed by the instance's transaction-quota subsystem, which tracks concurrent sessions and cumulative processing time per 60-second window. Exceeding the quota returns `HTTP 429`; the connector applies exponential backoff with jitter and retries up to the limit configured in the connector-job template. Operators seeing sustained 429s should review the transaction-quota configuration and, if necessary, reduce `sysparm_limit`.

### Incremental hook

The `sys_updated_on` column is present on every ServiceNow table and records the UTC-equivalent modification timestamp. The connector uses it as the high-water mark for all four CMDB tables: at the end of each run, the maximum observed `sys_updated_on` is persisted to the state table, and the next run issues a `sysparm_query` filter `sys_updated_on>javascript:gs.dateGenerate('{hwm}','start')`.

Time zone: although `sys_updated_on` is stored internally in UTC, the Table API renders it in the calling user's display time zone unless the profile specifies UTC. The connector's service account must be set to UTC, or the Bronze-to-Silver transform must convert using the instance's known offset. The reference implementation adopts the latter approach to decouple the connector from ServiceNow user-profile management.

ServiceNow supports webhook-style outbound notifications through Business Rules and Flow Designer, but this is not part of the standard Table API and requires custom application development. The reference implementation does not use it; the webhook-preferred rule falls through to the `sys_updated_on` high-water-mark strategy, which is adequate given that CMDB data changes on a daily rather than sub-minute cadence.

### Resource schema excerpt

The fields below are the subset consumed by the connector; complete schemas are available in the ServiceNow Table API and CMDB Instance API documentation.

*ServiceNow `cmdb_ci_business_app` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key; stable across updates. |
| `name` | string | Application display name. |
| `short_description` | string | Free-text summary. |
| `business_criticality` | reference | Tier (1--4 or custom values per instance; see Enumerations section below). |
| `operational_status` | reference | Lifecycle status (see Enumerations section below). |
| `owned_by` | reference (`sys_user_group`) | Owning team reference; resolved via join to `silver.teams`. |
| `sys_created_on` | datetime | Creation timestamp (normalized to UTC at transform). |
| `sys_updated_on` | datetime | High-water-mark column (normalized to UTC at transform). |

*ServiceNow `cmdb_rel_ci` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key of the relationship record. |
| `parent` | reference (`cmdb_ci`) | Source CI of the directed relationship. |
| `child` | reference (`cmdb_ci`) | Target CI of the directed relationship. |
| `type` | reference (`cmdb_rel_type`) | Relationship type label, e.g. *Depends on::Used by* or *Hosted on::Hosts*. |
| `sys_created_on` | datetime | Creation timestamp (normalized to UTC at transform). |
| `sys_updated_on` | datetime | High-water-mark column (normalized to UTC at transform). |

*ServiceNow `sys_user_group` consumed fields*

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (GUID) | Primary key; referenced by `owned_by` in `cmdb_ci_business_app`. |
| `name` | string | Group display name; becomes `team_name` in `silver.teams`. |
| `manager` | reference (`sys_user`) | Group manager; provides an escalation contact for security findings. |
| `email` | string | Group contact address; used as the notification address in gold-layer outputs. |
| `parent` | reference (`sys_user_group`) | Parent group; enables hierarchical team aggregations at the gold layer. |
| `sys_updated_on` | datetime | High-water-mark column (normalized to UTC at transform). |

### Enumerations

The `business_criticality` field uses integer-backed choice values. Default labels are `most_critical` (1), `somewhat_critical` (2), `less_critical` (3), and `not_critical` (4). Production deployments often extend or relabel these; the per-source `src/connectors/servicenow/severity.yml` lookup must be reviewed per instance before production use.

The `operational_status` field uses a separate integer choice list. Default labels are `operational` (1), `non-operational` (2), `ready` (3), `retired` (6), `pipeline` (7), and `in_maintenance` (8). Values are instance-configurable; `src/connectors/servicenow/status.yml` must be reviewed per deployment. The framework's canonical vocabulary maps all non-operational and retired values to a single `inactive` status to reduce branching in gold-layer computations.

### Quirks

**Custom fields.** Deployments routinely add organization-specific `u_`-prefixed attributes (e.g., `u_data_classification`). The bronze layer absorbs these via schema-on-read at landing: the raw payload is stored in `_raw_payload` and native columns are added via additive schema evolution, so no connector change is needed. Transformation mappings in `mapping.yml` must be updated only if a custom field is needed in silver or gold.

**Reference field resolution.** Reference fields (`owned_by`, `parent`) return a `sys_id` rather than a resolved sub-object with default parameters. The connector requests raw values via `sysparm_display_value=false` and `sysparm_exclude_reference_link=true`, preserving `sys_id` for silver-layer joins. The framework's separate-tables-plus-join strategy ingests all referenced tables independently; embedding resolved display names would introduce redundancy.

**Display value versus raw value.** `sysparm_display_value` accepts `false` (raw stored values; connector default), `true` (display strings), and `all` (both, nested). The connector always sets `false` so that reference fields contain stable `sys_id` GUIDs and choice fields contain integer codes; display strings are locale-dependent and change when administrators rename choices.

**Time zone normalization.** `sys_updated_on` and `sys_created_on` are rendered in the calling user's display time zone. The Bronze-to-Silver transform applies a `CONVERT_TIMEZONE` cast to UTC using the instance's known offset, stored as a connector configuration parameter. Operators must set this correctly per instance.

## Setup

### Configuration

Terraform provisions the ServiceNow integration automatically:

- `appsec_dev.bronze_servicenow.business_applications` and `appsec_dev.bronze_servicenow.app_cis` tables, fed by a Databricks **Lakeflow Connect** pipeline.
- `mvp-connectors` secret scope keys: `servicenow_url`, `servicenow_username`, `servicenow_password`.
- Two `cmdb_ci_business_app` records ("AppSec Demo Frontend", "AppSec Demo Backend") plus `cmdb_ci_appl` records for each seed repo, linked via `cmdb_rel_ci`.

### Bundle deployment

The Lakeflow Connect pipeline and Silver-transform job are created by `terraform apply` in `infra/terraform`. See [Platform → Terraform apply](../../platform/terraform-apply.md) for the full apply order.

### First run

Lakeflow Connect pipelines run on their own schedule once the connection is enabled; force a manual run:

```bash
PIPE_ID=$(terraform -chdir=infra/terraform output -raw servicenow_pipeline_id)
databricks pipelines start --pipeline-id "$PIPE_ID" --full-refresh
```

Wait ~2 minutes for the pipeline to complete. Check status in the Databricks UI under **Workflows → Lakeflow Pipelines**.

Observe bronze → silver:

```sql
-- Bronze: raw CMDB rows
SELECT * FROM appsec_dev.bronze_servicenow.business_applications LIMIT 10;

-- Silver (populated by the silver transform, scheduled separately)
SELECT application_id, name, owner_email, criticality FROM appsec_dev.silver_servicenow.applications;
```

Expected: 2 rows in `silver.applications` matching the two business-app names seeded by Terraform.

**Role in the evidence story.** Supplies the `silver.applications` and `silver.app_repo_mapping` rows that the [business-application rollup query](../../analytics/evidence.md#evidence-2-business-application-rollup) reads. Without ServiceNow, the "which business app has unresolved critical findings?" story collapses to just repo-level findings.

**Normalization spot-check.**

- Raw ServiceNow `business_criticality = '1 - critical'` → silver `criticality = 'critical'`.
- Raw `business_criticality = '2 - high'` → silver `criticality = 'high'`.

**Troubleshooting.**

| Symptom | Fix |
|---|---|
| Pipeline stuck on schema inference | Check `databricks_connection.servicenow` options; verify the admin user has read access to `cmdb_ci_business_app`. |
| `401 Unauthorized` | Rotate the admin password in tfvars, `terraform apply`, re-run pipeline. |
| 0 rows in bronze after successful run | PDI may lack the tables; confirm by hitting `/api/now/table/cmdb_ci_business_app?sysparm_limit=1` directly. |
| Silver transform job unscheduled | Verify `databricks_job.connector["servicenow"]` is running on schedule (see `terraform output connector_job_ids`). |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `src/connectors/servicenow/tests/test_ingest.py::test_auth_secret_resolution` | PASS |
| `REQ-ING-PAG` | `src/connectors/servicenow/tests/test_ingest.py::test_offset_pagination_two_pages` | PASS |
| `REQ-ING-RL` | `src/connectors/servicenow/tests/test_ingest.py::test_429_backoff_retries` | PASS |
| `REQ-ING-HWM` | `src/connectors/servicenow/tests/test_ingest.py::test_sys_updated_on_hwm_resume` | PASS |
| `REQ-TRF-MAP` | `src/connectors/servicenow/tests/test_transform.py::test_business_app_mapping` | PASS |
| `REQ-TRF-SEV` | — | N/A |
| `REQ-TRF-STS` | — | N/A |
| `REQ-TRF-TS` | `src/connectors/servicenow/tests/test_transform.py::test_sys_updated_on_utc_normalization` | PASS |
| `REQ-DQ` | `src/connectors/servicenow/tests/test_transform.py::test_business_app_expectation_quarantines_null_sys_id` | PASS |
| `REQ-DEDUP` | — | N/A |

Collected 7 requirement-bound tests via `pytest src/connectors/servicenow/tests/ -v --tb=short` (2026-04-22, 3.4 s wall-clock); 7 passed, 3 marked `N/A` because CMDB sources do not emit findings (no severity, status, or cross-tool deduplication apply).

### Tests

Tests live under [`src/connectors/servicenow/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/servicenow/tests). The report table above is the per-REQ outcome of running the bound tests in that directory.
