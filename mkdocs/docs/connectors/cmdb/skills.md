# CMDB skills

Three skills cover the connector lifecycle for CMDB sources. Each carries a CMDB specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: CMDB reference

Facts the analyze-source skill needs to write a complete Reference section for a CMDB source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. CMDB sources emit entities, not findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Do not apply: `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`. CMDB sources emit no findings, so severity, status, and cross tool deduplication are not exercised.

The ServiceNow column of the traceability matrix confirms this set: `REQ-TRF-SEV`, `REQ-TRF-STS`, and `REQ-DEDUP` are `N/A`.

### Default severity

N/A. CMDB sources emit no findings. The Enumerations sub-fact in the Reference section records this explicitly rather than fabricating a severity vocabulary.

### Incremental strategy

Native high water mark column (`updated_at` style; `sys_updated_on` in ServiceNow) is universal across CMDB sources per the capability contract. The connector advances the HWM per run and persists it to the state table. Webhook overlay is permitted where the source supports outbound notifications. Full reload is reserved for the rare case of a source exposing neither.

### Deduplication key

Not applicable. CMDB ingests entities (applications, teams, ownership), not findings. The standard dedup pattern targets `silver.findings` and is not exercised by entity ingestion.

### Target Silver tables

`silver.applications`, `silver.teams`, `silver.app_repo_mapping` per the Silver Entity Mapping requirements at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`. The Resource schema excerpt in the Reference section should map source fields to these standard entity columns.

### Authentication norms

Basic auth service account or OAuth 2.0 client credentials per the CMDB capability contract. The connector resolves credentials from the platform secret scope (REQ-ING-AUTH).

### Ingestion tooling preference

Standard preference order applies: Lakeflow Connect, then Databricks SDK, then dlt. CMDB sources are well served by Lakeflow Connect where a managed connector exists. Otherwise the SDK path covers the offset based pagination cleanly.

### Quirks

- **Custom attributes.** Schema on read at Bronze absorbs custom fields specific to the organization (for example `u_*` columns in ServiceNow) additively without connector changes. The Reference section MUST note this so generate-connector does not hard code a closed schema.
- **Reference fields.** Foreign key attributes such as `owned_by` return source side IDs. The connector reads them as opaque strings. Resolution against `silver.teams` happens via Bronze to Silver join, not at ingestion.
- **Display vs raw values.** ServiceNow and similar CMDBs default to display values that change with locale or admin renames. Connectors MUST request raw values to preserve stable IDs.
- **Relational data model.** Related CMDB tables (applications, teams, ownership) are ingested as separate Bronze tables and joined in Silver. They are never resolved at ingestion via relationship APIs.
- **Pagination scale.** Offset based pagination with page sizes in the thousands. Rate limit policy must accommodate the high page count typical of full reload bootstrapping.

*Rendered from `.claude/skills/analyze-source/references/cmdb.md`. Source of truth lives in the skill file.*

## generate-connector: CMDB reference

Facts the generate-connector skill needs to emit a CMDB connector module. CMDB sources emit entities, not findings.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below. Mark each with `@pytest.mark.requirement("REQ-...")`.

- Bind tests for: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Do NOT bind: `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`. The ServiceNow column of the traceability matrix marks these three N/A. The test suite MUST omit them.

### Default severity

N/A. CMDB sources emit no findings. The generated `src/connectors/{source}/severity.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# N/A: CMDB sources emit no findings
```

No mapping rows. The `mapping.yml` file does not reference this lookup.

### Incremental strategy

Native high water mark column (`updated_at` style; `sys_updated_on` for ServiceNow) per `references/cmdb.md` of `analyze-source`. Encode the column name in `config.yml` under `hwm_column`. The connector reads state from `src/platform/` HWM helpers. No scan-id, commit-SHA, or full reload paths apply.

### Deduplication key

Not applicable. The transform does NOT emit `dedup_links` rows for CMDB. Entity dedup is handled by the natural key column (`sys_id` or equivalent) at Bronze to Silver upsert time. Do NOT generate `dedup_links` linkage code in `transform.py`.

### Target Silver tables

Plural names, authoritative per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- `silver.applications`
- `silver.teams`
- `silver.app_repo_mapping`

Emit one Bronze to Silver mapping block per target table in `mapping.yml` (one block can produce multiple Silver rows via projection for each source; or split by source endpoint). Do NOT invent table names. `silver.ownership` is not a thing. Ownership lands in `silver.app_repo_mapping`.

The `mapping.yml` structure is entity only (no `category` discriminator, no severity / status lookup references). Field expressions follow the standard entity model at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`.

### Authentication norms

Basic auth service account or OAuth 2.0 client credentials. Read credentials from the platform secret scope in `ingest.py` via the helper in `src/platform/` (NOT inline `os.environ`). The `config.yml` references the secret scope keys by name only.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. CMDB sources are well served by Lakeflow Connect where a managed connector exists. Otherwise the SDK path covers offset based pagination cleanly. No CLI artefact override applies. Justify the chosen tool with one comment line at the top of `ingest.py`.

### Quirks

- **Schema on read at Bronze.** Custom attributes (e.g. `u_*` columns in ServiceNow) flow through additively without connector changes. Do NOT hard code a closed schema in `mapping.yml`. The standard fields project explicitly. Everything else falls through to Bronze for downstream use.
- **Reference fields.** Foreign key attributes (e.g. `owned_by`) are read as opaque strings. Do NOT resolve via relationship APIs at ingestion. Resolution lands at transform via Bronze to Silver join against `silver.teams`.
- **Display vs raw values.** Configure the source request to return raw values (e.g. `sysparm_display_value=false` for ServiceNow) so IDs stay stable across locale and admin renames.
- **Plural Silver names.** The transform writes to `silver.applications` / `silver.teams` / `silver.app_repo_mapping`. The plurals are authoritative. Singular forms are wrong.
- **High page count.** Offset based pagination with page sizes in the thousands. The `config.yml` page size knob defaults to 1000 unless the source documents otherwise.

*Rendered from `.claude/skills/generate-connector/references/cmdb.md`. Source of truth lives in the skill file.*

## validate-implementation: CMDB reference

Facts the validate-implementation skill needs to populate the Validation table for a CMDB connector. CMDB sources emit entities, not findings, so the test suite asserts entity shaped contracts only.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog" (keep table rows in catalog order). The ServiceNow column of the traceability matrix is the authoritative row for this category.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-PAG`
- `REQ-ING-RL`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-TS`
- `REQ-DQ`

Mark `N/A` (the Validation table row reads `N/A` with bound test cell as a dash):

- `REQ-TRF-SEV`: N/A. CMDB sources emit no findings, so severity normalization is not exercised. Per the matrix legend at `mkdocs/docs/platform/reference/catalog.md` § "Per-source traceability matrix": "the category does not exercise the requirement (e.g. CMDB sources emit no findings, so severity/status/dedup do not apply)".
- `REQ-TRF-STS`: N/A. Same rationale. Entities have no lifecycle status.
- `REQ-DEDUP`: N/A. Entity dedup is handled by the natural key column at Bronze to Silver upsert. There are no `dedup_links` rows for this category.

### Default severity

N/A. The test suite does NOT include a `test_severity_normalization`. `REQ-TRF-SEV` is N/A for this category. Cited in `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface": "CMDB data has no severity dimension."

### Incremental strategy

Native update timestamp HWM column (e.g. `sys_updated_on` for ServiceNow) per `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface". The test suite asserts HWM resume behaviour in a `test_hwm_resume` (or analogous) function bound to `REQ-ING-HWM`.

### Deduplication key

Not applicable. Entity dedup uses the natural key column at Bronze to Silver upsert. No `dedup_links` rows are emitted. The test suite does NOT include a `test_dedup_links` function. `REQ-DEDUP` is N/A.

### Target Silver tables

`silver.applications`, `silver.teams`, `silver.app_repo_mapping` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The test suite asserts schema mapping bound to `REQ-TRF-MAP` covers all three tables (one assertion or one test per table).

### Authentication norms

Basic auth service account or OAuth 2.0 client credentials per `mkdocs/docs/connectors/cmdb/index.md` § "Capability surface". The test suite asserts secret scope resolution (not inline `os.environ`) in `test_auth_secret_resolution` or analogous, bound to `REQ-ING-AUTH`.

### Ingestion tooling preference

Standard order: Lakeflow Connect, then Databricks SDK, then dlt. The test suite does not directly assert tool choice (that lives in `ingest.py`), but the auth / pagination / RL / HWM tests indirectly verify the chosen tool behaviour.

### Quirks

- **N/A rationale appended to summary.** When emitting the post table summary, include the standard phrase "marked `N/A` because CMDB sources do not emit findings (no severity, status, or cross tool deduplication apply)". This matches the wording in the existing baseline at `mkdocs/docs/connectors/cmdb/servicenow.md` § "## Validation".
- **Custom attributes do not change the REQ-ID set.** Schema on read at Bronze absorbs `u_*` style fields additively. Custom attribute coverage falls under `REQ-TRF-MAP`, not a new REQ-ID.
- **Reference fields read as opaque strings.** Foreign key fields (e.g. `owned_by`) are not resolved at ingest. The test suite asserts opaque string behaviour under `REQ-TRF-MAP`, not under a separate REQ-ID.
- **Display vs raw values.** Source side raw value mode (e.g. `sysparm_display_value=false`) is asserted under `REQ-TRF-MAP`. The schema mapping test verifies stable IDs across locales.
- **High page count.** Offset based pagination with page sizes in the thousands. The `REQ-ING-PAG` test asserts traversal across at least two pages without loss or duplication, per the catalog requirement text.

*Rendered from `.claude/skills/validate-implementation/references/cmdb.md`. Source of truth lives in the skill file.*
