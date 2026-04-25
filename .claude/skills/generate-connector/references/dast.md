# generate-connector — DAST reference

Facts the generate-connector skill needs to emit a DAST connector module. DAST sources emit findings against deployed targets; the HWM is scan-scoped, not record-level.

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

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- For server-based DAST consuming scan reports rather than the live API, `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes "the CLI-artefact ingestion path used by OWASP ZAP has no API auth, pagination, or rate limit." The ZAP traceability row marks these three N/A. Do NOT bind them in this case.
- For CI/CD-step DAST CLI artefacts, the same N/A pattern applies.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering the documented vocabulary (typically four levels: `Informational`, `Low`, `Medium`, `High`) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium` with a data-quality warning.

The `mapping.yml` `severity` field references the lookup file by path:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

## Incremental strategy

Scan-id-based, NOT record-level `updated_at`. Encode in `config.yml` under a `hwm_kind: scan_id` knob (or `hwm_kind: artefact_prefix` for CLI variants):

- **Server-based** (ZAP daemon / API): the scan ID is the high-water mark. The connector orchestrates scans per deployment and reads alerts back after scan completion. Encode the scan-orchestration mode (`scan-and-read` vs `read-only`) explicitly in `config.yml`.
- **CI/CD-step** (e.g. `zap-baseline.py`): the artefact file (object-storage prefix or pipeline artefact) is the high-water mark. Encode the prefix and report format (JSON / SARIF) in `config.yml`.

The `src/common/` HWM helpers expose a `scan_id` mode in addition to the column-based default; use it.

## Deduplication key

`(target, alert_id, uri_path)` per the DAST capability surface, also reflected in the Silver finding scope `(application_id, target, alert_id)` at `mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements`. Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["target"], row["alert_id"], row["uri_path"])
```

- `target` — the scanned deployment (host, base URL).
- `alert_id` — the scanner-internal rule identifier.
- `uri_path` — disambiguates multiple hits of the same rule across paths of the same target.

## Target Silver tables

`silver.findings` discriminated by `category="dast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "dast"` literally.

`transform.py` MUST emit a join against `silver.deployments` to resolve `target` (URL, host, port, path-prefix) into `application_id`. Unmatched targets are emitted unchanged for inventory-gap analysis (this is a deliberate completeness signal — do NOT drop rows; do NOT raise a DQ failure on the unmatched path). Code shape:

```python
silver_df = bronze_df.join(
    spark.table("silver.deployments"),
    on=match_target_expr,
    how="left",
)
```

The exact match expression depends on the source's `target` shape; the connector page documents it. Generate the join, do not stub it.

## Authentication norms

Style-dependent:

- **Server-based**: API key (e.g. `X-ZAP-API-Key` header for ZAP). `ingest.py` reads it via the helper in `src/common/`; `config.yml` references the secret-scope key name.
- **CI/CD-step / CLI-artefact**: no native auth on output files; access governed by object-storage IAM. `ingest.py` uses the autoloader / cloud-storage helpers; no auth code emitted.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **DAST scan-report ingestion is typically artefact-driven** — autoloader-style on the object-storage prefix is the canonical pattern. This is the documented exception to the preference order; justify in a top-of-file comment in `ingest.py`.
- Server-based DAST consuming a live API uses the SDK or dlt path.

## Quirks

- **Target vs file.** DAST findings reference a URL, not a repository file. The transform-time join against `silver.deployments` is mandatory; do NOT attempt application linkage at ingest. The generator MUST wire the join (see Target Silver tables above).
- **Inventory-gap analysis.** Unmatched targets are emitted unchanged — this is intentional. Do NOT generate filter logic that drops them.
- **Scan-scoped findings.** Each scan re-emits the full finding set within its scope. The connector treats scans as the unit of incremental work — record-level updates within a scan are not exposed by the source, so the transform MUST NOT attempt them.
- **No record-level `updated_at`.** This is the headline DAST quirk. The HWM is `scan_id` (or artefact filename) — encode it explicitly; do not fall back to a column-based HWM.
- **Scan orchestration vs report collection.** Server-based DAST connectors may need to drive scans (start, poll, read) rather than purely consume them. Encode the chosen mode in `config.yml`; emit the orchestration helpers from `src/common/` in `ingest.py` only when the source is in scan-and-read mode.

## operational.yml.databricks_runtime schema

Reverse-engineered from `git show a086f9d:src/connectors/owasp_zap/...` (no live DAST follower).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` `SCOPE="mvp-connectors"`; `config.yml` `bucket_secret_scope: mvp-connectors`. |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name: bronze_owasp_zap`. |
| `bronze_tables` | list[string] | yes | (none) | `config.yml` `bronze_table: ${catalog}.bronze_owasp_zap.findings`. |
| `cron_schedule` | string | yes | `0 */15 * * * ?` (every 15 min) | `resources/job.yml` `quartz_cron_expression`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/{schemas,volumes}.yml` `catalog_name`. |
| `job_name` | string | yes | `{source}-connector` | `resources/job.yml` `jobs.{job_name}`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `TARGET="${DATABRICKS_TARGET:-dev}"`. |
| `default_catalog` | string | no | `appsec_dev` | `scripts/install.sh` `CATALOG="${CATALOG:-appsec_dev}"`. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` put-secret lines. owasp_zap (server path): `(ZAP_URL→zap_url, ZAP_API_KEY→zap_api_key)`. CI/CD-step path uses bucket-only secrets. |
| `tool_source_label` | string | yes | `{source}` | Verify-step assumption. |
| `entry_wrappers` | bool | yes | `false` | a086f9d owasp_zap `resources/job.yml` `notebook_path: ../ingest.py` (no entry wrappers). |
| `bronze_volume` | string | yes | `{slug}_artifacts` (e.g. `zap_artifacts`) | `resources/volumes.yml` `volumes.{volume_key}.name`. owasp_zap=`zap_artifacts`. |
| `bronze_volume_storage_location` | string | yes | `s3://${var.artifact_bucket}/zap/` | `resources/volumes.yml` `storage_location`. |
| `cicd_prefix` | string | yes (CI/CD path) | (none) | `config.yml` `cicd_prefix: cicd/zap/`. |
| `scan_orchestration_mode` | enum(`scan-and-read`, `read-only`) | yes (server path) | `scan-and-read` | `config.yml` `scan_orchestration_mode:`. |
| `daemon_secrets` | dict | yes (server path) | (none) | `config.yml` `zap_api_url_secret: zap_url` and `zap_api_key_secret: zap_api_key` — secret-scope keys read by ingest.py. Mirrors `databricks_runtime.secret_env_vars` for the server path. |
| `hwm_kind` | enum(`scan_id`, `artefact_prefix`) | yes | `artefact_prefix` | `config.yml` `hwm_kind:`. owasp_zap=`artefact_prefix` (preferred — CI/CD-step path). |

17 fields.

**Judgment call:** DAST has TWO sub-shapes (CI/CD-step CLI artefact + server daemon). owasp_zap a086f9d encodes BOTH in one config — `secret_env_vars` covers the daemon path; `cicd_prefix` covers the artefact path. `daemon_secrets` is the cleaner restatement for skill consumption.

## Databricks-side production-shape

### scripts/load-secrets.sh template

Same shape as SCM. Daemon-path secret_env_vars dominate.

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
#
# Reads from environment variables:
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}  — <purpose>
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

Full three-step shape with verify-step querying `silver.findings WHERE tool_source`. Mirrors a086f9d owasp_zap install.sh.

```bash
#!/usr/bin/env bash
# install.sh — end-to-end installer for the {{ source }} connector.
# (See SCM/SAST template — same three-step shape.)

set -euo pipefail
{% for entry in databricks_runtime.secret_env_vars %}
: "${{ '{' }}{{ entry.env_var }}:?{{ entry.env_var }} is required{{ '}' }}"
{% endfor %}

TARGET="${DATABRICKS_TARGET:-{{ databricks_runtime.default_target }}}"
CATALOG="${CATALOG:-{{ databricks_runtime.default_catalog }}}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading {{ source }} secrets..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the {{ databricks_runtime.job_name }} job (target=${TARGET})..."
databricks bundle run {{ databricks_runtime.job_name }} --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "    SELECT count(*) FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.findings;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}';"
else
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.findings"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}'"
fi

echo "OK: {{ source }} connector install complete."
```

### install.sh (top-level) template

Same chain. DAST source-side runtime varies — daemon path uses `hashicorp/aws` or `hashicorp/kubernetes` for the daemon container; CI/CD-step path uses `hashicorp/null` (no provisioning needed).

### *_entry.py applicability

**N/A for DAST** in current owasp_zap shape (`entry_wrappers=false`). `resources/job.yml` points at `../ingest.py` directly. If a future DAST source needs notebook-widget wrappers (e.g. complex scan orchestration), set `entry_wrappers=true` and use the SCM-shaped template.

### sql/<envelope>.sql template

**N/A for DAST.** owasp_zap a086f9d does not emit a `sql/` directory. Bronze tables are populated by `ingest.py` directly (Auto Loader on the `cicd_prefix` for the CI/CD-step path; REST writes for the daemon path).

### resources/extras (per category)

- `resources/job.yml` (8-file core) with `notebook_path: ../ingest.py` / `../transform.py`. 15-min cron.
- `resources/schemas.yml` — `bronze_{source}` only:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
  ```

- `resources/volumes.yml` — REQUIRED. UC Volume backing the `cicd_prefix`:

  ```yaml
  resources:
    volumes:
      {{ databricks_runtime.bronze_volume }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        schema_name: {{ databricks_runtime.bronze_schema }}
        name: {{ databricks_runtime.bronze_volume }}
        volume_type: EXTERNAL
        storage_location: {{ databricks_runtime.bronze_volume_storage_location }}
  ```

- `resources/connection.yml` — **N/A** (API key via dbutils.secrets, not UC connection).
- `resources/pipeline.yml` — **N/A**.

### Page §4–§7 templates

#### §Secrets (page §4)

```markdown
## Secrets

Loaded into the `{{ databricks_runtime.secret_scope }}` secret scope by `src/connectors/{{ source }}/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
{% for entry in databricks_runtime.secret_env_vars %}
| `{{ entry.secret_key }}` | `{{ entry.env_var }}` | <daemon-path purpose> |
{% endfor %}

```bash
{% for entry in databricks_runtime.secret_env_vars %}
export {{ entry.env_var }}="..."
{% endfor %}
bash src/connectors/{{ source }}/scripts/load-secrets.sh
```
```

#### §Run the job (page §5)

```markdown
## Run the job

The {{ source }} ingestion is a notebook job named `{{ databricks_runtime.job_name }}` that runs every 15 minutes once enabled. Trigger an on-demand run:

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a one-shot orchestration (load secrets + run + verify):

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```

The job has two tasks: `ingest` (Auto Loader on `{{ databricks_runtime.cicd_prefix }}` for CI/CD-step artefacts; REST against the daemon for `scan-and-read` mode) and `transform` (Bronze → silver.findings).
```

#### §Verify (page §6)

```markdown
## Verify

```sql
{% for tbl in databricks_runtime.bronze_tables %}
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};
{% endfor %}

SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}' AND category = 'dast';
```
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| Daemon path `401 Unauthorized` | `ZAP_API_KEY` does not match the daemon's configured key. Update both, re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh`. |
| 0 rows in `{{ databricks_runtime.bronze_schema }}.findings` | CI/CD-step path: no artefacts under `{{ databricks_runtime.cicd_prefix }}`. Daemon path: no scans executed. Check the corresponding source. |
| Application linkage missing in silver | The transform-time join against `silver.deployments` did not match the `target` URL. Verify deployment rows exist with matching host. |
```
