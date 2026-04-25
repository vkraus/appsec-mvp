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

## Setup

!!! info "Pending implementation"
    The Setup section is stubbed. The connector module under `src/connectors/servicenow/` is regenerated by the `generate-connector` skill in the next phase of the regenerate-4-originals work. Once the module lands, this section describes secret-loading via `src/connectors/servicenow/scripts/load-secrets.sh`, bundle deployment via `databricks bundle deploy --target dev`, and the on-demand run command `databricks bundle run servicenow-connector --target dev`.

## Validation

!!! info "Pending validation"
    The Validation section is stubbed. The `validate-implementation` skill populates the per-REQ outcome table after the connector module is generated and its pytest suite runs. CMDB-applicable REQs are `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, and `REQ-DQ`. `REQ-TRF-SEV`, `REQ-TRF-STS`, and `REQ-DEDUP` are marked N/A because CMDB sources do not emit findings (no severity, status, or cross-tool deduplication apply).

## Generation log

This connector page is produced by the connector-lifecycle skills under the regenerate-4-originals work. Row 1 below is filled by `analyze-source` on this run; rows 2 and 3 are placeholders for `generate-connector` and `validate-implementation`.

| Stage              | Skill                              | Inputs                                                                                                                                  | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (cmdb)            | name=ServiceNow; url=https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI; category=cmdb (release: Yokohama)  | mkdocs/docs/connectors/cmdb/servicenow.md sections 1 to 3                          | 2026-04-25 | 3cd1028 (regenerate-4-originals)         |
| Module generation  | `generate-connector` (cmdb)        | (pending)                                                                                                                               | (pending)                                                                          | (pending)  | (pending)                                |
| Validation         | `validate-implementation` (cmdb)   | (pending)                                                                                                                               | (pending)                                                                          | (pending)  | (pending)                                |

## References

- ServiceNow Table API reference (latest, redirects to release-pinned page; release at run time: Yokohama): [https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI](https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI)
- ServiceNow Table API reference (Yokohama, version-pinned URL): [https://www.servicenow.com/docs/r/yokohama/api-reference/rest-apis/c_TableAPI.html](https://www.servicenow.com/docs/r/yokohama/api-reference/rest-apis/c_TableAPI.html)
- CMDB category capability contract: [Connectors > CMDB](index.md)
- Standard mapping (Silver Entity Mapping Requirements): [Standard mapping](../../platform/reference/canonical-mapping.md#silver-entity-mapping-requirements)
- analyze-source CMDB skill reference: [CMDB skills](skills.md#analyze-source-cmdb-reference)
