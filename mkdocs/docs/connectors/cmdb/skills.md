# CMDB skills

Four skills cover the connector lifecycle for CMDB sources. Each carries a CMDB specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

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

## provision-source: CMDB reference

Facts the provision-source skill needs to emit the source-side runtime for a CMDB source. CMDB tenants are SaaS, so the runtime is a thin **Terraform SaaS-seed** module that POSTs demo CMDB records to the user's tenant via the source's REST table API. It is optional. Users with an already-populated CMDB skip it.

### Runtime shape

`runtime_provisioner: terraform-saas-seed`. Provider stack: `hashicorp/http` only. There is no AWS, no Kubernetes, no IRSA — pure HTTP. Mutating writes (POSTs to the table API) flow through `terraform_data` + `local-exec curl` because the ServiceNow / generic-CMDB table API has no first-class Terraform provider.

The runtime emits the standard four-file shape (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`) plus `README.md` and `install.sh`. There are no `runtime/files/*` sidecars by default — seeded records are constructed inline in `main.tf` from `var.seed_repo_names` and a hardcoded business-app spec.

### `operational.yml.source_runtime` fields

Required: `runtime_provisioner` (always `terraform-saas-seed` for CMDB), `instance_url_var_name` (default `instance_url`), `admin_username_var_name` (default `admin_username`), `admin_password_var_name` (default `admin_password`).

Optional, with category-baked defaults: `seed_repo_names_default` (`["BenchmarkJava", "BenchmarkPython", "juice-shop"]`), `github_org_default` (`appsec-mvp-demo`), `project_prefix_default` (`appsec-mvp`), `business_apps` (Frontend / Backend split with criticality), `table_endpoints` (`["cmdb_ci_business_app", "cmdb_ci_appl", "cmdb_rel_ci"]`), `relationship_type` (`"Depends on::Used by"`), `apply_prerequisites` (`["bash", "curl", "jq"]`), `terraform_required_version` (`>= 1.7`).

### Variables exposed

Required (no defaults): `instance_url`, `admin_username`, `admin_password` (sensitive). Optional with category defaults: `github_org`, `seed_repo_names`, `project_prefix`.

### Outputs

`business_app_sysids` — map of seeded business-app names to ServiceNow `sys_id` values (looked up via `data "http"` after each POST).

### `runtime/install.sh` shape

Wraps `terraform init` + `terraform apply -auto-approve` with TF_VAR exports drawn from operator-supplied env vars (`{SOURCE_UPPER}_INSTANCE_URL`, `{SOURCE_UPPER}_ADMIN_USERNAME`, `{SOURCE_UPPER}_ADMIN_PASSWORD`, plus optional `SEED_REPO_NAMES` and `PROJECT_PREFIX`). The script enforces `bash`, `curl`, and `jq` on PATH (the `local-exec` provisioners shell out to them) and exits non-zero with a clear message if any required env var is unset.

> **Apply prerequisites note:** on Windows hosts, run from WSL or Git Bash. The `local-exec` provisioners are not idempotent against an already-populated CMDB — re-running against the same tenant skips records whose `triggers_replace` keys are unchanged but does not detect drift if records were edited manually in the UI between applies. Taint the relevant `terraform_data` resources before re-applying if needed.

### Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`. Body is a two-paragraph operator-facing summary: what the module seeds (demo business-app and CI records via REST), how to run it (`cd src/connectors/{source}/runtime && terraform init && terraform apply -var-file=terraform.tfvars`, or `bash runtime/install.sh`), and a cross-link to `runtime/README.md` for the full variable list. Closes with the apply-prerequisites callout (`bash`, `curl`, `jq`).

*Rendered from `.claude/skills/provision-source/references/cmdb.md`. Source of truth lives in the skill file.*

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

### Databricks-side production-shape

In addition to the eight-file core (`config.yml`, `ingest.py`, `transform.py`, `mapping.yml`, `severity.yml`, `status.yml`, `resources/{source}-job.yml`, and the `tests/` suite), generate-connector also emits the **Databricks-side production-shape** for CMDB connectors. The skill reads `operational.yml.databricks_runtime` (a sibling sub-block to `source_runtime`) to interpolate the templates.

The `databricks_runtime` schema for CMDB is reverse-engineered from the ServiceNow follower's pre-deletion state and covers thirteen fields: `secret_scope` (default `mvp-connectors`), `bronze_schema` (default `bronze_{source}`), `silver_schema` (default `silver_{source}` — CMDB is the only category that emits the silver schema; downstream Silver lives there), `bronze_tables`, `envelope_table`, `cron_schedule`, `uc_catalog_var`, `lakeflow_pipeline_name`, `lakeflow_connection_name`, `lakeflow_source_objects`, `default_target`, `default_catalog`, `secret_env_vars`, and `dab_connection_var_passthrough` (always `true` for CMDB — Lakeflow Connect's UC connection pulls credentials from DAB variables at deploy time, not from the secret scope).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from the operator's environment. Iterates over `databricks_runtime.secret_env_vars` (each entry is `{env_var, secret_key}`) and runs `databricks secrets put-secret` per pair.
- **`scripts/install.sh`** — end-to-end installer wrapping load-secrets + Lakeflow pipeline trigger (`databricks bundle run {lakeflow_pipeline_name} --refresh-all`) + verify-row-counts. CMDB-specific: triggers a **Lakeflow pipeline** (not a notebook job), and the verify step counts rows in each `bronze_tables` entry plus `silver.applications`.
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy --target {default_target}`. Pass `--skip-runtime` to skip the source-side runtime when the source is already provisioned (e.g. SaaS-only CMDB tenants).
- **`sql/<envelope>.sql`** — Bronze envelope **VIEW overlay** (not `CREATE TABLE`) over the Lakeflow-managed table. Projects the standard §2.2.2 metadata columns (`_ingestion_timestamp`, `_source_system`, `_batch_id`, `_raw_payload`, `_hwm_value`) on top of the source-native columns. CMDB envelopes are views because Lakeflow Connect owns the physical schema.
- **`resources/` extras** — alongside `resources/{source}-job.yml`, CMDB emits `resources/schemas.yml` (declares both `bronze_{source}` AND `silver_{source}` schemas), `resources/connection.yml` (the UC Lakeflow Connect connection reading from DAB variables `${var.{source}_host}` / `${var.{source}_username}` / `${var.{source}_password}`), and `resources/pipeline.yml` (the Lakeflow Connect pipeline with `ingestion_definition.objects[]` mapping each source table to its bronze destination). `resources/volumes.yml` is N/A for CMDB — Lakeflow Connect handles persistence.
- **No `*_entry.py` wrappers** — Lakeflow Connect owns the ingest path; the `resources/job.yml` `notebook_path` points to `../ingest.py` and `../transform.py` directly.
- **Connector page §4–§7 templates** — `generate-connector` also fills in the page sections it owns: §Secrets (table mapping `secret_key` ↔ `env_var` with the load-secrets command), §Run the job (CMDB-specific — triggers a Lakeflow pipeline via `--refresh-all` rather than a notebook job), §Verify (Bronze row counts per Lakeflow-defined table plus `silver.app_repo_mapping` cross-source check), and §Troubleshooting (pipeline-stuck-on-schema-inference, `401 Unauthorized` rotation pointing at `BUNDLE_VAR_{source}_password=...` to keep secrets off `argv`/history, 0-rows-after-success, and the cross-source repository_id resolution path).

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
