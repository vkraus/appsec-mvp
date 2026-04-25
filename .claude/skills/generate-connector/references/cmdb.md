# generate-connector — CMDB reference

Facts the generate-connector skill needs to emit a CMDB connector module. CMDB sources emit entities, not findings.

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

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below; mark each with `@pytest.mark.requirement("REQ-...")`.

- Bind tests for: `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Do NOT bind: `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`. The traceability matrix's ServiceNow column marks these three N/A; the test suite MUST omit them.

## Default severity

N/A — CMDB sources emit no findings. The generated `config/severity/{source}.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# N/A — CMDB sources emit no findings
```

No mapping rows. The `mapping.yml` file does not reference this lookup.

## Incremental strategy

Native high-water-mark column (`updated_at`-style; `sys_updated_on` for ServiceNow) per `references/cmdb.md` of `analyze-source`. Encode the column name in `config.yml` under `hwm_column`. The connector reads state from `src/common/` HWM helpers; no scan-id, commit-SHA, or full-reload paths apply.

## Deduplication key

Not applicable. The transform does NOT emit `dedup_links` rows for CMDB; entity dedup is handled by the natural-key column (`sys_id` or equivalent) at Bronze-to-Silver upsert time. Do NOT generate `dedup_links` linkage code in `transform.py`.

## Target Silver tables

Plural names, authoritative per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- `silver.applications`
- `silver.teams`
- `silver.app_repo_mapping`

Emit one Bronze→Silver mapping block per target table in `mapping.yml` (one block can produce multiple Silver rows via per-source projection; or split by source endpoint). Do NOT invent table names — `silver.ownership` is not a thing; ownership lands in `silver.app_repo_mapping`.

The `mapping.yml` shape is entity-only (no `category` discriminator, no severity / status lookup references). Field expressions follow the canonical entity model at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-entity-mapping-requirements`.

## Authentication norms

Basic-auth service account or OAuth 2.0 client-credentials. Read credentials from the platform secret scope in `ingest.py` via the helper in `src/common/` (NOT inline `os.environ`). The `config.yml` references the secret-scope keys by name only.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. CMDB sources are well-served by Lakeflow Connect where a managed connector exists; otherwise the SDK path covers offset-based pagination cleanly. No CLI-artefact override applies. Justify the chosen tool with one comment line at the top of `ingest.py`.

## Quirks

- **Schema-on-read at Bronze.** Custom attributes (e.g. `u_*` columns in ServiceNow) flow through additively without connector changes. Do NOT hard-code a closed schema in `mapping.yml` — the canonical fields project explicitly; everything else falls through to Bronze for downstream use.
- **Reference fields.** Foreign-key attributes (e.g. `owned_by`) are read as opaque strings; do NOT resolve via relationship APIs at ingestion. Resolution lands at transform via Bronze-to-Silver join against `silver.teams`.
- **Display vs raw values.** Configure the source request to return raw values (e.g. `sysparm_display_value=false` for ServiceNow) so IDs stay stable across locale and admin renames.
- **Plural Silver names.** The transform writes to `silver.applications` / `silver.teams` / `silver.app_repo_mapping` — the plurals are authoritative. Singular forms are wrong.
- **High page count.** Offset-based pagination with page sizes in the thousands; `config.yml` page-size knob defaults to 1000 unless the source documents otherwise.

## operational.yml.databricks_runtime schema

Reverse-engineered from `git show a086f9d:src/connectors/servicenow/...` (the only CMDB source; pre-deletion state).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` line `SCOPE="mvp-connectors"`; also referenced in `scripts/install.sh` "Loading … into the mvp-connectors scope". |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name: bronze_servicenow`; `resources/pipeline.yml` `target: bronze_servicenow`; `sql/business_applications_envelope.sql` `${catalog}.bronze_servicenow.business_applications_envelope`. |
| `silver_schema` | string | yes | `silver_{source}` | `resources/schemas.yml` `name: silver_servicenow` (second schema entry alongside bronze). |
| `bronze_tables` | list[string] | yes | (none) | `resources/pipeline.yml` `objects[].table.destination_table` — Lakeflow Connect lands these (e.g. `business_applications`, `app_cis`); `sql/<envelope>.sql` overlays one of them. |
| `envelope_table` | string | yes | (none) | `sql/<envelope>.sql` filename and `CREATE OR REPLACE VIEW ${catalog}.bronze_servicenow.business_applications_envelope` — the table that gets the §2.2.2 metadata overlay. |
| `cron_schedule` | string | yes | `0 0 * * * ?` (hourly) | `resources/job.yml` `quartz_cron_expression`; `resources/pipeline.yml` `schedule.quartz_cron_expression`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/{schemas,pipeline}.yml` `catalog_name: ${var.catalog}` and `catalog: ${var.catalog}`. |
| `lakeflow_pipeline_name` | string | yes | `{source}_ingest` | `resources/pipeline.yml` `pipelines.{key}` and `name:` (e.g. `servicenow_ingest`); `scripts/install.sh` `databricks bundle run servicenow_ingest --refresh-all`. |
| `lakeflow_connection_name` | string | yes | `{source}` | `resources/connection.yml` `connections.{key}` and `name:` (e.g. `servicenow`); referenced by `pipeline.yml` `ingestion_definition.connection_name`. |
| `lakeflow_source_objects` | list[{source_schema,source_table,destination_table}] | yes | (none) | `resources/pipeline.yml` `ingestion_definition.objects[].table` — per-Lakeflow-table mapping. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `TARGET="${DATABRICKS_TARGET:-dev}"`. |
| `default_catalog` | string | no | `appsec_dev` | `scripts/install.sh` `CATALOG="${CATALOG:-appsec_dev}"`. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` `databricks secrets put-secret "$SCOPE" <secret_key> --string-value "$<env_var>"` lines. ServiceNow: `(SERVICENOW_URL→servicenow_url, SERVICENOW_USERNAME→servicenow_username, SERVICENOW_PASSWORD→servicenow_password)`. |
| `dab_connection_var_passthrough` | bool | yes | `true` | `resources/connection.yml` reads `${var.servicenow_host}` / `${var.servicenow_username}` / `${var.servicenow_password}` — DAB variables, not secret-scope reads. CMDB uses Lakeflow Connect's UC connection, which pulls credentials from the bundle vars at deploy time (see top-of-file comment in `load-secrets.sh`). |

13 fields.

## Databricks-side production-shape

What `generate-connector` emits for the CMDB category. Templates use `{{ source }}`, `{{ category }}` for skill-input substitution and `{{ databricks_runtime.<field> }}` for `operational.yml` interpolation.

### scripts/load-secrets.sh template

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
#
# These secrets are also the values the {{ source }} Lakeflow connection
# (declared in src/connectors/{{ source }}/resources/connection.yml) reads
# at deploy time via DAB variables. Pushing them to the secret scope as
# well lets the connector job use them via dbutils.secrets when reading
# from non-Lakeflow paths (e.g. ad-hoc REST calls).
#
# Reads from environment variables:
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}  — <purpose from page §Secrets>
{% endfor %}
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

{% for entry in databricks_runtime.secret_env_vars %}
: "${{ '{' }}{{ entry.env_var }}:?{{ entry.env_var }} is required{{ '}' }}"
{% endfor %}

SCOPE="{{ databricks_runtime.secret_scope }}"

{% for entry in databricks_runtime.secret_env_vars %}
databricks secrets put-secret "$SCOPE" {{ entry.secret_key }} --string-value "${{ entry.env_var }}"
{% endfor %}

echo "OK: {{ source }} secrets loaded into scope $SCOPE"
```

### scripts/install.sh template

End-to-end installer wrapping load-secrets + Lakeflow pipeline trigger + verify-row-counts. CMDB-specific shape: triggers the Lakeflow pipeline (not a notebook job) via `--refresh-all`.

```bash
#!/usr/bin/env bash
# install.sh — end-to-end installer for the {{ source }} connector.
#
# Wraps the three steps a fresh user runs to take an empty Databricks
# workspace + an existing {{ source }} tenant from zero to populated bronze
# rows in `{{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.bronze_tables[0] }}`
# and silver CMDB rows in `{{ databricks_runtime.default_catalog }}.silver.applications`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `{{ databricks_runtime.secret_scope }}`
#     secret scope, and the `silver` schema exist; `databricks bundle deploy
#     --target {{ databricks_runtime.default_target }}` has been run from the repo root at
#     least once so the `{{ databricks_runtime.bronze_schema }}` schema and the
#     `{{ databricks_runtime.lakeflow_pipeline_name }}` pipeline are registered).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or
#     a configured `~/.databrickscfg` profile).
#
# Required env vars
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}  — <purpose>
{% endfor %}
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "{{ databricks_runtime.default_target }}".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If
#                       unset, the verify step is skipped with a notice.
#   CATALOG           — Unity Catalog name. Defaults to "{{ databricks_runtime.default_catalog }}".
#
# Idempotent: re-runs overwrite secret values and re-trigger the pipeline.

set -euo pipefail

{% for entry in databricks_runtime.secret_env_vars %}
: "${{ '{' }}{{ entry.env_var }}:?{{ entry.env_var }} is required{{ '}' }}"
{% endfor %}

TARGET="${DATABRICKS_TARGET:-{{ databricks_runtime.default_target }}}"
CATALOG="${CATALOG:-{{ databricks_runtime.default_catalog }}}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading {{ source }} secrets into the {{ databricks_runtime.secret_scope }} scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the {{ databricks_runtime.lakeflow_pipeline_name }} pipeline (target=${TARGET})..."
databricks bundle run {{ databricks_runtime.lakeflow_pipeline_name }} --target "${TARGET}" --refresh-all

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
{% for tbl in databricks_runtime.bronze_tables %}
  echo "    SELECT count(*) FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};"
{% endfor %}
  echo "    SELECT count(*) FROM ${CATALOG}.silver.applications;"
else
{% for tbl in databricks_runtime.bronze_tables %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_{{ tbl }}_bronze FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }}"
{% endfor %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_apps_silver FROM ${CATALOG}.silver.applications"
fi

echo "OK: {{ source }} connector install complete."
```

### install.sh (top-level) template

Top-level orchestrator chaining `runtime/install.sh` (provision-source emit) → `scripts/load-secrets.sh` → `databricks bundle deploy`. CMDB sources are typically SaaS, so `runtime/install.sh` is often a no-op smoke-test.

```bash
#!/usr/bin/env bash
# Top-level orchestrator for the {{ source }} connector.
#
# Runs in this order:
#   1. src/connectors/{{ source }}/runtime/install.sh
#      (source-side terraform; emitted by provision-source)
#   2. src/connectors/{{ source }}/scripts/load-secrets.sh
#      (writes secrets into the {{ databricks_runtime.secret_scope }} scope)
#   3. databricks bundle deploy --target {{ databricks_runtime.default_target }}
#      (registers the {{ databricks_runtime.lakeflow_connection_name }} UC connection,
#       the {{ databricks_runtime.bronze_schema }} schema, and the
#       {{ databricks_runtime.lakeflow_pipeline_name }} Lakeflow pipeline).
#
# Pass --skip-runtime to skip step 1 (use when the source is already provisioned
# or when running on SaaS without a runtime dependency).

set -euo pipefail
SKIP_RUNTIME=0
for arg in "$@"; do
  case "$arg" in --skip-runtime) SKIP_RUNTIME=1 ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

if [[ "$SKIP_RUNTIME" -eq 0 && -x "${SCRIPT_DIR}/runtime/install.sh" ]]; then
  echo "Step 1/3: Provisioning source runtime..."
  bash "${SCRIPT_DIR}/runtime/install.sh"
else
  echo "Step 1/3: Skipping source runtime."
fi

echo "Step 2/3: Loading secrets..."
bash "${SCRIPT_DIR}/scripts/load-secrets.sh"

echo "Step 3/3: Deploying bundle..."
databricks bundle deploy --target "${DATABRICKS_TARGET:-{{ databricks_runtime.default_target }}}"

echo "OK: {{ source }} connector installed."
```

### *_entry.py applicability

**N/A for CMDB.** Lakeflow Connect owns the ingest path; there is no notebook ingest task to wrap. The `resources/job.yml` `tasks.ingest.notebook_path` points to `../ingest.py` directly (a thin contract-wrapper that records the BatchDescriptor — emitted by the 8-file core, not a separate `ingest_entry.py`). `transform_entry.py` is also not emitted; the transform task points to `../transform.py`.

### sql/<envelope>.sql template

CMDB envelopes are **VIEW overlays** (not `CREATE TABLE`) because Lakeflow Connect owns the physical schema. The view projects the §2.2.2 metadata columns on top of the Lakeflow-managed table.

```sql
-- Bronze envelope overlay for {{ source }} {{ databricks_runtime.envelope_table }}.
--
-- Lakeflow Connect owns the physical bronze schema. This view projects
-- the section 2.2.2 envelope on top of it so downstream readers see the
-- uniform metadata alongside source-native columns.
--
-- The Lakeflow ingestion metadata columns (_rescued_data, and the
-- snapshot/sync timestamps populated by the ingestion pipeline) are
-- the source of truth for _ingestion_timestamp and _batch_id. Verify
-- the column names against the deployed pipeline before merging: the
-- Lakeflow column names vary by connector version. If they differ,
-- update the CAST and aliases here rather than the pipeline config.

CREATE OR REPLACE VIEW {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }}_envelope AS
SELECT
  CAST(_sync_timestamp AS TIMESTAMP) AS _ingestion_timestamp,
  '{{ source }}' AS _source_system,
  _sync_run_id AS _batch_id,
  to_json(struct(*)) AS _raw_payload,
  CAST(_sync_timestamp AS STRING) AS _hwm_value,
  *
FROM {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }};
```

### resources/extras (per category)

CMDB emits ALL FOUR resource fragments alongside `resources/job.yml`:

- `resources/schemas.yml` — `bronze_{source}` AND `silver_{source}` (CMDB is the only category that emits the silver schema; downstream Silver sits there). Template:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
      {{ databricks_runtime.silver_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.silver_schema }}
  ```

- `resources/connection.yml` — Unity Catalog Lakeflow Connect connection. Template:

  ```yaml
  resources:
    connections:
      {{ databricks_runtime.lakeflow_connection_name }}:
        name: {{ databricks_runtime.lakeflow_connection_name }}
        connection_type: {{ source | upper }}
        comment: "{{ source | title }} CMDB — Lakeflow Connect"
        options:
          host: ${var.{{ source }}_host}
          username: ${var.{{ source }}_username}
          password: ${var.{{ source }}_password}
  ```

- `resources/pipeline.yml` — Lakeflow Connect pipeline. Template:

  ```yaml
  resources:
    pipelines:
      {{ databricks_runtime.lakeflow_pipeline_name }}:
        name: {{ databricks_runtime.lakeflow_pipeline_name }}
        catalog: {{ databricks_runtime.uc_catalog_var }}
        target: {{ databricks_runtime.bronze_schema }}
        continuous: false
        schedule:
          quartz_cron_expression: "{{ databricks_runtime.cron_schedule }}"
          timezone_id: UTC
        ingestion_definition:
          connection_name: {{ databricks_runtime.lakeflow_connection_name }}
          objects:
  {% for obj in databricks_runtime.lakeflow_source_objects %}
            - table:
                source_schema: {{ obj.source_schema }}
                source_table: {{ obj.source_table }}
                destination_catalog: {{ databricks_runtime.uc_catalog_var }}
                destination_schema: {{ databricks_runtime.bronze_schema }}
                destination_table: {{ obj.destination_table }}
  {% endfor %}
  ```

- `resources/volumes.yml` — **N/A for CMDB.** Lakeflow Connect handles persistence; no UC Volume required.

`resources/job.yml` (already emitted by the 8-file core) for CMDB has `notebook_path: ../ingest.py` / `../transform.py` (NOT `*_entry.py`) and a `quartz_cron_expression` matching `databricks_runtime.cron_schedule`.

### Page §4–§7 templates

The connector page (`mkdocs/docs/connectors/{{ category }}/{{ slug }}.md`) gets these sections; reverse-engineered from `git show a086f9d:mkdocs/docs/connectors/cmdb/servicenow.md`.

#### §Secrets (page §4)

```markdown
## Secrets

Loaded into the `{{ databricks_runtime.secret_scope }}` secret scope by `src/connectors/{{ source }}/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
{% for entry in databricks_runtime.secret_env_vars %}
| `{{ entry.secret_key }}` | `{{ entry.env_var }}` | <purpose from analyze-source page §3> |
{% endfor %}

Run from repo root after Phase 1 completes:

```bash
{% for entry in databricks_runtime.secret_env_vars %}
export {{ entry.env_var }}="..."
{% endfor %}
bash src/connectors/{{ source }}/scripts/load-secrets.sh
# Expected: OK: {{ source }} secrets loaded into scope {{ databricks_runtime.secret_scope }}
```
```

#### §Run the job (page §5)

CMDB-specific: triggers a **Lakeflow pipeline** via `--refresh-all`, NOT a notebook job.

```markdown
## Run the job

The {{ source }} ingestion is a **Lakeflow Connect pipeline** rather than a notebook job. The pipeline is named `{{ databricks_runtime.lakeflow_pipeline_name }}` (declared in `src/connectors/{{ source }}/resources/pipeline.yml`) and runs on the configured cron once enabled. Trigger an on-demand full refresh:

```bash
databricks bundle run {{ databricks_runtime.lakeflow_pipeline_name }} --target dev --refresh-all
```

For a one-shot orchestration (load secrets + run + verify counts), use the wrapper:

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```

Wait ~2 minutes. Pipeline status is visible under **Workflows → Lakeflow Pipelines** in the Databricks UI.
```

#### §Verify (page §6)

```markdown
## Verify

```sql
-- Bronze: raw CMDB rows landed by Lakeflow Connect.
{% for tbl in databricks_runtime.bronze_tables %}
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};
{% endfor %}

-- Cross-source canonical app↔repo mapping — joins application_id (CMDB) to
-- repository_id (SCM). Schema: src/platform/sql/silver_tables.sql.
SELECT application_id, repository_id, linked_at FROM {{ databricks_runtime.default_catalog }}.silver.app_repo_mapping;
```

Expected: bronze rows for each Lakeflow-defined table; rows in `silver.app_repo_mapping` whose `repository_id` does not appear in `silver.repositories` indicate the SCM connector has not yet ingested the referenced repositories.
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| Pipeline stuck on schema inference | Open the connection definition in the Databricks UI (**Catalog → External Data → Connections → {{ databricks_runtime.lakeflow_connection_name }}**) and verify the service account has read access to the configured source tables. |
| `401 Unauthorized` from the pipeline | Rotate the password at the source, re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh`, *and* re-deploy the bundle so the UC connection picks up the new password (pass via `BUNDLE_VAR_{{ source }}_password=...` rather than `--var` to keep the value off `argv`/history). Then trigger a new pipeline run. |
| 0 rows in bronze after a successful run | The source tenant may not expose the configured tables. Confirm by hitting the source REST endpoint directly with `curl`. |
| `silver.app_repo_mapping` rows have `repository_id` values not present in `silver.repositories` | Install at least one SCM connector and run it before expecting the cross-source join to resolve. |
```
