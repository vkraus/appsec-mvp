# analyze-source — CMDB reference

Facts the analyze-source skill needs to write a complete Reference section for a CMDB source.

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

From `mkdocs/docs/platform/reference/catalog.md`. CMDB sources emit entities, not findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Do not apply: `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP` — CMDB sources emit no findings, so severity, status, and cross-tool deduplication are not exercised.

The traceability matrix's ServiceNow column confirms this set: `REQ-TRF-SEV`, `REQ-TRF-STS`, and `REQ-DEDUP` are `N/A`.

## Default severity

N/A. CMDB sources emit no findings. The Reference section's Enumerations sub-fact records this explicitly rather than fabricating a severity vocabulary.

## Incremental strategy

Native high-water-mark column (`updated_at`-style; `sys_updated_on` in ServiceNow) is universal across CMDB sources per the capability surface. The connector advances the HWM per run and persists it to the state table. Webhook overlay is permitted where the source supports outbound notifications. Full reload is reserved for the rare case of a source exposing neither.

## Deduplication key

Not applicable. CMDB ingests entities (applications, teams, ownership), not findings. The canonical dedup pattern targets `silver.findings` and is not exercised by entity ingestion.

## Target Silver tables

`silver.applications`, `silver.teams`, `silver.app_repo_mapping` per the Silver Entity Mapping requirements at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`. The Reference section's Resource schema excerpt should map source fields to these canonical entity columns.

## Authentication norms

Basic-auth service account or OAuth 2.0 client-credentials per the CMDB capability surface. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. CMDB sources are well-served by Lakeflow Connect where a managed connector exists; otherwise the SDK path covers the offset-based pagination cleanly.

## Quirks

- **Custom attributes.** Schema-on-read at Bronze absorbs organization-specific custom fields (for example `u_*` columns in ServiceNow) additively without connector changes. The Reference section MUST note this so generate-connector does not hard-code a closed schema.
- **Reference fields.** Foreign-key attributes such as `owned_by` return source-side IDs. The connector reads them as opaque strings; resolution against `silver.teams` happens via Bronze-to-Silver join, not at ingestion.
- **Display vs raw values.** ServiceNow and similar CMDBs default to display values that change with locale or admin renames. Connectors MUST request raw values to preserve stable IDs.
- **Relational data model.** Related CMDB tables (applications, teams, ownership) are ingested as separate Bronze tables and joined in Silver — never resolved at ingestion via relationship APIs.
- **Pagination scale.** Offset-based pagination with page sizes in the thousands; rate-limit policy must accommodate the high page count typical of full-reload bootstrapping.

## Lakeflow Connect availability

ServiceNow appears in the analyze-source LFC managed-source catalogue (Table API v2) and the cmdb category is in scope. Resolution: `databricks_runtime.ingestion_path = lakeflow_connect`. The Reference section gains the catalogue-citation sentence per SKILL.md procedure step 9 (the resolution step).

Future CMDB sources outside the catalogue fall through to the category-canonical default (`sdk_dlt`) — REST + offset pagination + `updated_at`-style HWM column.
