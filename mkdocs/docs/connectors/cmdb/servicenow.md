# ServiceNow

## Overview

ServiceNow is the reference implementation for the CMDB category. The connector treats a ServiceNow instance as the authoritative business-application inventory and team-ownership graph. It reads from the ServiceNow Table API over the `cmdb_ci_business_app` Configuration Item table (and related CI tables when an instance models ownership separately) to populate the standard Silver entity tables `silver.applications`, `silver.teams`, and `silver.app_repo_mapping`. The downstream effect is that `silver.findings` rows produced by every other connector resolve to a real business application through the `repository_id` to `silver.repositories` to `silver.app_repo_mapping` chain.

**Category:** CMDB (entity-only; no findings emitted) - **Integration pattern:** REST + Databricks SDK, offset-based pagination over `/api/now/table/{tableName}`.

ServiceNow's data model is relational: applications, teams, and ownership relationships live in separate CI tables and reference each other through foreign-key attributes (`owned_by`, `used_by`, etc.). Per the [CMDB capability contract](index.md#capability-contract), the connector ingests each related table as its own Bronze table and joins them in Silver rather than resolving relationships at ingestion via the relationship API. Custom attributes (organisation-specific `u_*` columns) flow through additively under schema-on-read at Bronze without connector changes.

CMDB sources do not emit findings, so severity and status normalisation are not exercised. `REQ-TRF-SEV`, `REQ-TRF-STS`, and `REQ-DEDUP` are marked N/A on the [traceability matrix](../../platform/reference/catalog.md). The lookup files at `src/connectors/servicenow/severity.yml` and `src/connectors/servicenow/status.yml` exist (the framework contract requires both files for every connector) but contain only a single comment line: `# N/A: CMDB sources emit no findings`. No mapping rows.

Bronze schema: `bronze_servicenow`. Cross-source contribution: every other connector's `silver.findings` rows resolve to a business application through the entity tables this connector populates.

## Prerequisites

ServiceNow exposes the Table API on every instance, including the free Personal Developer Instance (PDI) tier. The PDI is the recommended path for thesis demos: zero infrastructure, the same Table API surface as production, and pre-loaded sample CMDB data sufficient to exercise the connector end-to-end. Self-hosted is not an option for ServiceNow; the platform is SaaS-only.

| Input | Where to obtain | Used as |
|---|---|---|
| Instance hostname | After signing up at [https://developer.servicenow.com/](https://developer.servicenow.com/) and requesting a Personal Developer Instance, the instance is provisioned at `https://devXXXXXX.service-now.com` (the six-digit identifier is assigned to your account). Production tenants follow the same `https://<instance>.service-now.com` convention. | Env var `SERVICENOW_INSTANCE`; secret-scope key `servicenow_instance`. |
| Service-account username | A dedicated integration user with read access to `cmdb_ci_business_app` and the related CI tables the connector queries. On a PDI, create the user at **All > User Administration > Users** and assign the `itil` role for read access to the CMDB. On production, the security team typically pre-provisions an integration account; the role required is read-only on the CI tables, not write. | Env var `SERVICENOW_USER`; secret-scope key `servicenow_user`. |
| Service-account password | Set when creating the user. ServiceNow does not expose API tokens for Basic auth; the password is the credential. Store it only in the platform secret scope. | Env var `SERVICENOW_PASSWORD`; secret-scope key `servicenow_password`. |

!!! tip "Personal Developer Instance vs production tenant"
    The PDI is the recommended path for thesis demos: it provisions a full ServiceNow instance with sample CMDB data in minutes and the Table API behaviour is identical to production. PDIs hibernate after a few days of inactivity; wake the instance at [https://developer.servicenow.com/](https://developer.servicenow.com/) before triggering the connector. Production tenants use the same connector configuration; only the hostname and service-account credentials change.

## Reference

### API scope

ServiceNow exposes the **Table API** at the URL pattern `https://<instance>.service-now.com/api/now/table/{tableName}`. The Table API is a generic REST surface over the platform's record store: every CI table (and every non-CMDB table the platform manages) is reachable through the same endpoint with the table name as the path parameter. The connector consumes it via `GET` for read-only ingestion; write verbs are not used.

Endpoints consumed by the connector:

- `GET /api/now/table/cmdb_ci_business_app` - the primary endpoint. Returns one record per business application. This is the source of `silver.applications`.
- `GET /api/now/table/{ownership_table}` - one or more related CI tables that model team ownership in the target instance. ServiceNow does not impose a single ownership model: many instances express it via the `owned_by` field on `cmdb_ci_business_app` itself (which references `sys_user_group`); some carry a dedicated relationship table. The connector reads the chosen table(s) per the `tables` list in `src/connectors/servicenow/config.yml`. The records populate `silver.teams` and `silver.app_repo_mapping` after Silver-side joins.

Authentication uses **HTTP Basic** with a service-account username and password resolved from the platform secret scope. ServiceNow also supports OAuth 2.0 client credentials, and the CMDB capability contract permits either; the reference implementation uses Basic auth because PDIs do not require OAuth setup and the credential surface is simpler. Production tenants that mandate OAuth can swap the auth mode in `ingest.py` without touching the rest of the connector. The framework helper resolves credentials from the platform secret scope (REQ-ING-AUTH) - the connector never reads `os.environ` directly.

The Table API is a documented public REST API; no SDK or GraphQL surface is consumed.

### Pagination and rate limits

The Table API uses **offset-based pagination** controlled by two query parameters:

- `sysparm_offset` - zero-based starting index of the page.
- `sysparm_limit` - number of records returned per page.

The connector default is `sysparm_limit = 1000` per the CMDB category convention (page sizes in the thousands). The connector iterates by advancing `sysparm_offset` by the page size until the server returns fewer records than `sysparm_limit` (the standard end-of-data signal for offset pagination). The Table API exposes a `Link` header with `rel="next"` for clients that prefer link-following; the connector treats it as advisory and relies on the offset arithmetic.

Rate limiting on ServiceNow is governed by **inbound REST API rate limit rules** configured at the instance level. ServiceNow does not publish a single global quota; administrators define per-user, per-role, or per-source-IP limits and the platform returns `HTTP 429 Too Many Requests` with a `Retry-After` header on breach. Response headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` are exposed when rate-limit rules are active. The connector applies exponential backoff on `429` per `REQ-ING-RL` and respects `Retry-After` when present.

Full-reload bootstrapping of a large CMDB (tens of thousands of CIs) generates a high page count; the rate-limit policy must accommodate this, especially on shared production instances. PDIs and dedicated integration tenants have no practical rate-limit ceiling for the volumes typical of the AppSec use case.

### Incremental hook

The high-water mark column is **`sys_updated_on`**, a native datetime column ServiceNow maintains on every record. The connector persists the maximum observed `sys_updated_on` per table to the platform state store and replays from that watermark on the next run.

The HWM filter is expressed via the Table API's `sysparm_query` parameter using ServiceNow's encoded-query syntax: `sys_updated_on>=YYYY-MM-DD HH:MM:SS`. The query is ordered by `sys_updated_on` ascending (`ORDERBYsys_updated_on`) to make pagination resumable across runs. Records updated within the same second as the previous watermark are re-read on the next run; downstream Bronze-to-Silver upserts deduplicate on `sys_id` (the natural key), so this is idempotent.

ServiceNow supports outbound webhooks via Business Rules and the Webhook Notification capability, which a deployment can wire to fire on `cmdb_ci_business_app.update`. The reference implementation does not consume webhooks; scheduled polling on the `sys_updated_on` HWM is sufficient for the AppSec refresh cadence (once per pipeline run). A future overlay is permitted per the CMDB capability contract.

Full-reload mode is reserved for the first run (when the HWM is unset) and for explicit operator-driven reseed.

### Resource schema excerpt

The fields below are the subset the connector reads from `cmdb_ci_business_app`. ServiceNow's actual schema for the table is much wider (hundreds of platform-system columns plus organisation-specific `u_*` extensions); the connector projects only the fields that participate in the standard mapping. Schema-on-read at Bronze captures every other column additively without connector changes per the CMDB category quirks.

**`cmdb_ci_business_app` consumed fields**

| Field | Type | Meaning |
|---|---|---|
| `sys_id` | string (32-char GUID) | Primary key; stable across renames and admin edits. Used as `natural_key` on `silver.applications`. |
| `name` | string | Display name of the business application; lands as a domain column on `silver.applications`. |
| `short_description` | string | One-line description of the application; optional domain column. |
| `business_criticality` | string | Criticality classification (typical values: `1 - most critical`, `2 - somewhat critical`, `3 - less critical`, `4 - not critical`). Domain column on `silver.applications`; not normalised to a category-canonical scale because CMDB has no severity dimension. |
| `operational_status` | string | Lifecycle state of the application (e.g. `operational`, `non-operational`, `retired`). Domain column. |
| `owned_by` | string (sys_id reference) | Reference to a `sys_user` or `sys_user_group` row that owns the application. Read as an opaque string; resolved against the team table at Silver join time, not at ingestion (per the *Reference fields* quirk). |
| `used_by` | string (sys_id reference) | Reference to a consuming team or department. Same treatment as `owned_by`. |
| `sys_created_on` | datetime (instance TZ) | Record creation timestamp; lands as `valid_from` on `silver.applications` after UTC conversion. |
| `sys_updated_on` | datetime (instance TZ) | Most recent modification timestamp; the HWM column. Format: `YYYY-MM-DD HH:MM:SS`, instance-local timezone (see Quirks). |
| `u_*` (organisation-specific) | various | Custom attributes added by the deploying organisation. Not enumerated; flow through additively at Bronze. |

The ownership-table read (whichever table the deployment uses for team modelling) follows the same pattern: project the natural key (`sys_id`), display columns (`name`), the foreign-key references that link to applications, and `sys_updated_on` for HWM. The exact column list is per-deployment and is captured in the connector's `mapping.yml` for the chosen table.

### Application code (`u_app_id` → `app_code`)

The ServiceNow transform projects the custom column `u_app_id` from `cmdb_ci_business_app` to `silver.applications.app_code`. Only values matching the regex `^\d{5}$` exactly survive — empty strings, non-digit characters, and 4- or 6-digit values all coerce to `NULL`. The 5-digit form is the join key for the [app-repo linker](../../platform/app-repo-link.md), which extracts the same 5-digit token from repository names and joins back to `silver.applications.app_code`.

If a deployment does not use 5-digit application codes, leave `u_app_id` unpopulated. The `app_code` column will be `NULL` for those applications and the name-based linker will skip them; the existing `u_repository_id` path remains available for explicit per-application linking.

### Enumerations

**Severity.** N/A. CMDB sources emit no findings, so the standard four-level severity model (`critical`, `high`, `medium`, `low`) is not exercised. The lookup file `src/connectors/servicenow/severity.yml` contains only the comment `# N/A: CMDB sources emit no findings`. No mapping rows. The `mapping.yml` does not reference this lookup.

**Status.** N/A. CMDB entities have no finding lifecycle. The standard five-state status model (`open`, `confirmed`, `resolved`, `false_positive`, `wontfix`) does not apply. The lookup file `src/connectors/servicenow/status.yml` contains the same comment. `operational_status` on `cmdb_ci_business_app` is an entity lifecycle attribute, not a finding status, and lands as a domain column on `silver.applications` without normalisation against the finding-status canonical model.

**Dedup.** N/A. Entity dedup is handled by the natural key (`sys_id`) at Bronze-to-Silver upsert time. The connector does not emit `dedup_links` rows; cross-tool finding deduplication does not apply to CMDB.

### Quirks

- **Instance-local timestamps.** ServiceNow returns datetime fields (including `sys_updated_on` and `sys_created_on`) as strings in the format `YYYY-MM-DD HH:MM:SS`, encoded in the **instance-local timezone** rather than UTC. The connector normalises them to UTC at the Bronze-to-Silver transform per `REQ-TRF-TS`. The instance timezone is read once from the system property `glide.sys.timezone` (or supplied via `config.yml` on instances where the property is not exposed to API readers) and used as the offset for parsing. Failing to convert produces a silent UTC-skew bug that the data-quality expectations would not catch.
- **Empty fields render as empty strings.** ServiceNow renders missing or null field values as the empty string `""` rather than JSON `null`. The Bronze-to-Silver transform coerces empty strings to `NULL` for all nullable columns to keep the Silver schema honest. This applies to optional columns like `short_description` and to reference columns when the relationship is unset.
- **Display vs raw values.** By default the Table API returns *display values* for reference fields (e.g. `owned_by` resolves to the human-readable group name) and for choice fields (e.g. `business_criticality` resolves to the localised label). Display values are unstable: they change with locale and admin renames, breaking joins. The connector requests **raw values** by setting `sysparm_display_value=false` on every Table API call so foreign keys come back as `sys_id` strings and choice fields come back as their canonical underlying values. Resolution against `silver.teams` happens via Bronze-to-Silver join at the transform layer.
- **Reference link expansion.** The Table API's default response inlines a `link` URL alongside every reference field's value (`{"value": "<sys_id>", "link": "<api-url>"}`). The connector sets `sysparm_exclude_reference_link=true` to flatten reference fields to bare `sys_id` strings, simplifying the Bronze schema and reducing payload size on full-reload bootstraps.
- **Custom attributes (`u_*` columns).** Organisations routinely extend `cmdb_ci_business_app` with custom columns prefixed `u_` (e.g. `u_compliance_scope`, `u_data_classification`). The connector's `mapping.yml` projects only the standard fields the AppSec model consumes; everything else falls through to Bronze additively under schema-on-read. `generate-connector` MUST NOT hard-code a closed schema.
- **Relational data model, joined in Silver.** Applications, teams, and ownership are separate CI tables. The connector reads each as its own Bronze table; the join into `silver.applications` / `silver.teams` / `silver.app_repo_mapping` happens at the Silver transform layer, never at ingestion via the ServiceNow relationship API. This keeps the ingestion path stateless and the relationship logic testable without API mocks.
- **High page count on bootstrap.** Offset-based pagination at `sysparm_limit=1000` over a large CMDB (tens of thousands of CIs) produces dozens of pages on the first run. The rate-limit and backoff policy in `ingest.py` is sized for this; subsequent incremental runs typically retrieve a single page.
- **Personal Developer Instance hibernation.** PDIs hibernate after a few days of inactivity. The Table API returns `HTTP 200` with an HTML wake-up page rather than JSON when the instance is asleep. The connector treats a non-JSON `Content-Type` on a Table API response as a hard error with a clear remediation message ("wake the instance at developer.servicenow.com") rather than landing the HTML payload in Bronze.

## Optional source runtime

The optional Terraform module under [`src/connectors/servicenow/runtime/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/servicenow/runtime) seeds **demo CMDB records** in the servicenow tenant via the REST table API. It is **pure HTTP** — no AWS, no Kubernetes, no IAM. Users with an already-populated CMDB skip this entirely.

Required runtime inputs: `instance_url`, `admin_username`, `admin_password`. Optional: `seed_repo_names` (default `["BenchmarkJava", "BenchmarkPython", "juice-shop"]`), `github_org` (default `appsec-mvp-demo`), `project_prefix` (default `appsec-mvp`).

Apply prerequisites: `bash`, `curl`, and `jq` must be on PATH (the `local-exec` provisioners shell out to them). On Windows, run from WSL or Git Bash.

Apply with:

```bash
cd src/connectors/servicenow/runtime
terraform init
terraform apply -var-file=terraform.tfvars
```

Or wrap the apply via the bundled `install.sh`:

```bash
export SERVICENOW_INSTANCE_URL=https://devXXXXX.service-now.com
export SERVICENOW_ADMIN_USERNAME=admin
export SERVICENOW_ADMIN_PASSWORD=...
bash src/connectors/servicenow/runtime/install.sh
```

The output `business_app_sysids` echoes the seeded record sys_ids for downstream wiring. See [`src/connectors/servicenow/runtime/README.md`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/servicenow/runtime) for the full variable list and override flags.

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/servicenow/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `servicenow_url` | `SERVICENOW_URL` | ServiceNow instance URL (e.g. `https://devXXXXX.service-now.com`). |
| `servicenow_username` | `SERVICENOW_USERNAME` | Service-account username with `itil` (or read-only on the consumed CI tables) role. |
| `servicenow_password` | `SERVICENOW_PASSWORD` | Service-account password. |

Run from repo root after Phase 1 completes:

```bash
export SERVICENOW_URL="https://devXXXXX.service-now.com"
export SERVICENOW_USERNAME="..."
export SERVICENOW_PASSWORD="..."
bash src/connectors/servicenow/scripts/load-secrets.sh
# Expected: OK: servicenow secrets loaded into scope mvp-connectors
```

## Run the job

The servicenow ingestion is a **Lakeflow Connect pipeline** rather than a notebook job. The pipeline is named `servicenow_ingest` (declared in `src/connectors/servicenow/resources/pipeline.yml`) and runs on the configured cron once enabled. Trigger an on-demand full refresh:

```bash
databricks bundle run servicenow_ingest --target dev --refresh-all
```

For a one-shot orchestration (load secrets + run + verify counts), use the wrapper:

```bash
bash src/connectors/servicenow/scripts/install.sh
```

Wait ~2 minutes. Pipeline status is visible under **Workflows → Lakeflow Pipelines** in the Databricks UI.

## Verify

```sql
-- Bronze: raw CMDB rows landed by Lakeflow Connect.
SELECT count(*) FROM appsec_dev.bronze_servicenow.business_applications;
SELECT count(*) FROM appsec_dev.bronze_servicenow.app_cis;

-- Cross-source canonical app↔repo mapping — joins application_id (CMDB) to
-- repository_id (SCM). Schema: src/platform/sql/silver_tables.sql.
SELECT application_id, repository_id, linked_at FROM appsec_dev.silver.app_repo_mapping;
```

Expected: bronze rows for each Lakeflow-defined table; rows in `silver.app_repo_mapping` whose `repository_id` does not appear in `silver.repositories` indicate the SCM connector has not yet ingested the referenced repositories.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Pipeline stuck on schema inference | Open the connection definition in the Databricks UI (**Catalog → External Data → Connections → servicenow**) and verify the service account has read access to the configured source tables. |
| `401 Unauthorized` from the pipeline | Rotate the password at the source, re-run `bash src/connectors/servicenow/scripts/load-secrets.sh`, *and* re-deploy the bundle so the UC connection picks up the new password (pass via `BUNDLE_VAR_servicenow_password=...` rather than `--var` to keep the value off `argv`/history). Then trigger a new pipeline run. |
| 0 rows in bronze after a successful run | The source tenant may not expose the configured tables. Confirm by hitting the source REST endpoint directly with `curl`. |
| `silver.app_repo_mapping` rows have `repository_id` values not present in `silver.repositories` | Install at least one SCM connector and run it before expecting the cross-source join to resolve. |
| PDI returns HTML instead of JSON | The Personal Developer Instance is hibernating. Wake it at [https://developer.servicenow.com/](https://developer.servicenow.com/) and re-trigger the pipeline. |

## Validation

| Requirement | Bound test | Outcome |
|---|---|---|
| REQ-ING-AUTH | src/connectors/servicenow/tests/test_ingest.py::test_ingest_contract_rejects_missing_credentials | PASS |
| REQ-ING-PAG | src/connectors/servicenow/tests/test_ingest.py::test_offset_pagination_concatenates_pages_without_duplication | PASS |
| REQ-ING-RL | src/connectors/servicenow/tests/test_ingest.py::test_pdi_hibernation_response_raises_with_clear_remediation | PASS |
| REQ-ING-HWM | src/connectors/servicenow/tests/test_ingest.py::test_build_sysparm_query_emits_hwm_filter | PASS |
| REQ-TRF-MAP | src/connectors/servicenow/tests/test_transform.py::test_normalise_application_projects_canonical_fields | PASS |
| REQ-TRF-SEV | — | N/A |
| REQ-TRF-STS | — | N/A |
| REQ-TRF-TS | src/connectors/servicenow/tests/test_transform.py::test_servicenow_datetime_converts_europe_berlin_to_utc | PASS |
| REQ-DQ | src/connectors/servicenow/tests/test_transform.py::test_empty_string_values_coerce_to_none_on_application | PASS |
| REQ-DEDUP | — | N/A |

Run summary: 10 collected, 0.36s, 7 PASS / 0 FAIL / 3 N/A. N/A rationale: CMDB sources emit no findings, so severity / status / dedup are not exercised — REQ-TRF-SEV / REQ-TRF-STS / REQ-DEDUP marked N/A per references/cmdb.md.

## Implementation log

This connector page is produced by the connector-lifecycle skills under the regenerate-4-originals work. Row 1 below is filled by `analyze-source` on this run; rows 2, 3, and 4 are filled by `provision-source`, `generate-connector`, and `validate-implementation`.

| Stage              | Skill                              | Inputs                                                                                                                                  | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (cmdb)            | name=ServiceNow; url=https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI; category=cmdb (release: Yokohama)  | mkdocs/docs/connectors/cmdb/servicenow.md sections 1 to 3                          | 2026-04-25 | 3cd1028 (regenerate-4-originals)         |
| Source provisioning | `provision-source` (cmdb) | source_runtime fields=runtime_provisioner, terraform_required_version, instance_url_var_name, admin_username_var_name, admin_password_var_name, seed_repo_names_default, github_org_default, project_prefix_default, business_apps, table_endpoints, relationship_type, apply_prerequisites | src/connectors/servicenow/runtime/, mkdocs/docs/connectors/cmdb/servicenow.md §Source provisioning | 2026-04-25 | b230852 (split-source-and-databricks-skills) |
| Module generation | `generate-connector` (cmdb) | page hash=8a528887f162; databricks_runtime fields=secret_scope, bronze_schema, silver_schema, bronze_tables, envelope_table, cron_schedule, uc_catalog_var, lakeflow_pipeline_name, lakeflow_connection_name, lakeflow_source_objects, default_target, default_catalog, secret_env_vars, dab_connection_var_passthrough | src/connectors/servicenow/__init__.py, src/connectors/servicenow/config.yml, src/connectors/servicenow/ingest.py, src/connectors/servicenow/transform.py, src/connectors/servicenow/mapping.yml, src/connectors/servicenow/severity.yml, src/connectors/servicenow/status.yml, src/connectors/servicenow/tests/, src/connectors/servicenow/scripts/install.sh, src/connectors/servicenow/scripts/load-secrets.sh, src/connectors/servicenow/install.sh, src/connectors/servicenow/sql/business_applications_envelope.sql, src/connectors/servicenow/resources/job.yml, src/connectors/servicenow/resources/schemas.yml, src/connectors/servicenow/resources/connection.yml, src/connectors/servicenow/resources/pipeline.yml, mkdocs/docs/connectors/cmdb/servicenow.md §4–§7 | 2026-04-25 | b230852 (split-source-and-databricks-skills) |
| Validation | `validate-implementation` (cmdb) | module path=src/connectors/servicenow/ | mkdocs/docs/connectors/cmdb/servicenow.md §5 | 2026-04-25 | 7fec0ac (regenerate-4-originals) |

## References

- ServiceNow Table API reference (latest, redirects to release-pinned page; release at run time: Yokohama): [https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI](https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI)
- ServiceNow Table API reference (Yokohama, version-pinned URL): [https://www.servicenow.com/docs/r/yokohama/api-reference/rest-apis/c_TableAPI.html](https://www.servicenow.com/docs/r/yokohama/api-reference/rest-apis/c_TableAPI.html)
- CMDB category capability contract: [Connectors > CMDB](index.md)
- Standard mapping (Silver Entity Mapping Requirements): [Standard mapping](../../platform/reference/canonical-mapping.md#silver-entity-mapping-requirements)
- analyze-source CMDB skill reference: [CMDB skills](skills.md#analyze-source-cmdb-reference)
