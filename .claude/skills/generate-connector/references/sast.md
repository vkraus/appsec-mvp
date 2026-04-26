# generate-connector — SAST reference

> **Ingestion path:** SAST sources resolve to `dlt` (server-based REST: SonarQube), `artifact_path` (CLI: Semgrep), or — when a maintained Python SDK is added to the analyze-source catalogue — `sdk`. The `lakeflow_connect` branch is documented in `cmdb.md`; templates here cover the non-LFC branches.

Facts the generate-connector skill needs to emit a SAST connector module. SAST sources emit code-level findings.

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

- Server-based SAST (full ten REQ-IDs apply per the SonarQube and Semgrep traceability rows): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- CLI-based SAST (artefact ingestion): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A — the catalog notes the CLI-artefact path "has no API auth, pagination, or rate limit." Do NOT bind these three.
- Platform-integrated SAST (hosted inside the SCM platform): inherits the SCM connector's auth, pagination, and rate-limit code; bind only the transform / DQ / dedup REQ-IDs locally and document the inherited bindings in a comment.

## Default severity

`medium`. Generate `config/severity/{source}.yml` covering every documented source value (e.g. `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, `INFO` for SonarQube; `ERROR`, `WARNING`, `INFO` for Semgrep) mapped to the canonical four-level model (`critical`, `high`, `medium`, `low`). Undocumented values fall through to `medium` with a data-quality warning per the helper in `src/common/`.

The `mapping.yml` `severity` field references the lookup file by path, NOT a hard-coded value:

```yaml
severity:
  source_path: <native-severity-field>
  lookup: config/severity/{source}.yml
```

## Incremental strategy

Selection depends on deployment style; encode in `config.yml`:

- **Server-based**: native update-timestamp HWM column (e.g. `updated_at`, `creationDate`, `last_scan_finished_at`). Default mode.
- **CLI-based**: full-reload from object-storage prefix or pipeline artefact; HWM is the commit SHA or scan-start timestamp recorded in the artefact filename.
- **Platform-integrated**: inherit the SCM platform's webhook or `updated_at` hook.

## Deduplication key

The dedup tuple `(repository_id, file_path, rule_id)` matches the SAST capability surface at [`mkdocs/docs/connectors/sast/index.md`](../../../../mkdocs/docs/connectors/sast/index.md) § "Canonical mapping contribution" and is consistent with the canonical Silver Finding shape at [`mkdocs/docs/platform/reference/canonical-mapping.md`](../../../../mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements). Encode this tuple literally in `transform.py` when building `dedup_links` rows:

```python
dedup_key = (row["repository_id"], row["file_path"], row["rule_id"])
```

The transform MUST also project `source_finding_id` (the source-side stable identifier — SonarQube `key`; Semgrep `id` for Cloud or `check_id`+`path`+`line` for CLI) for cross-run linkage.

## Target Silver tables

`silver.findings` discriminated by `category="sast"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "sast"` literally.

## Authentication norms

PAT or API-key based across all three deployment styles. `ingest.py` reads credentials via the helper in `src/common/`; `config.yml` references the secret-scope key names only. For CLI-based connectors, no API auth applies — IAM on the artefact bucket governs access.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- Server-based SAST is well-served by the SDK or dlt path (paginated REST).
- **CLI-based SAST is the documented exception** — emit a CLI-artefact ingest path (e.g. `httpx` for cloud-storage APIs, or autoloader on the object-storage prefix) and justify the deviation in a top-of-file comment in `ingest.py`. This is one of the two CLI-artefact exceptions called out in `CLAUDE.md` (alongside secrets / Semgrep Docker).
- Platform-integrated SAST shares the host SCM connector's pagination/auth helpers (note this in the top-of-file comment).

## Quirks

- **Operational pattern axis.** The `config.yml` HWM shape changes between CI/CD-step (commit SHA / run ID) and periodic-global (updated-since timestamp) modes. Encode the chosen mode explicitly; do not leave it inferred.
- **CWE category.** Project the source's CWE identifier alongside `rule_id` in `mapping.yml`; downstream classification depends on it.
- **Severity vocabulary breadth.** Some tools use BLOCKER … INFO; others use CRITICAL … LOW or numeric scales. The severity lookup MUST be exhaustive over the documented vocabulary; no gaps.
- **CLI-artefact path.** When the source is CLI-based, `config.yml` encodes the object-storage prefix (or pipeline-artefact pattern) and the SARIF / JSON format flavour; `ingest.py` uses autoloader-style ingestion via `src/common/` helpers.
- **Rule-pack drift.** Rule IDs may shift across rule-pack versions; the dedup key embeds `rule_id` as-is. Document any source-side stability guarantees in a transform-level comment.

## operational.yml.databricks_runtime schema

Reverse-engineered from `src/connectors/sonarqube/...` (server-based SAST follower) and `git show a086f9d:src/connectors/semgrep/...` (CLI-artefact SAST original). SAST has TWO sub-shapes; schema fields are conditional on `databricks_runtime.deployment_style`.

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `deployment_style` | enum(`server`, `cli_artefact`) | yes | (none) | `config.yml`. sonarqube=server (REST API + token); semgrep=cli_artefact (S3 artefact prefixes). |
| `secret_scope` | string | yes (server) / yes (cli) | `mvp-connectors` | `scripts/load-secrets.sh` `SCOPE="mvp-connectors"`. Server uses it for API token; CLI uses it for artefact-bucket pointer. |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name:`. sonarqube=`bronze_sonarqube`; semgrep=`bronze_semgrep`. |
| `bronze_tables` | list[string] | yes | (none) | sonarqube install.sh: `bronze_sonarqube.issues`. semgrep install.sh: `bronze_semgrep.findings`. |
| `cron_schedule` | string | yes | `0 */30 * * * ?` (server) / `0 */15 * * * ?` (cli) | `resources/job.yml` `quartz_cron_expression`. sonarqube=30-min; semgrep=15-min. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/schemas.yml` `catalog_name`. |
| `job_name` | string | yes | `{source}-connector` | `resources/job.yml` `jobs.{job_name}`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `TARGET="${DATABRICKS_TARGET:-dev}"`. |
| `default_catalog` | string | no | `appsec_dev` | `scripts/install.sh` `CATALOG="${CATALOG:-appsec_dev}"`. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes (server) / partial (cli) | (none) | `scripts/load-secrets.sh` put-secret lines. sonarqube: `(SONARQUBE_URL→sonarqube_url, SONARQUBE_TOKEN→sonarqube_token)`. semgrep: `(ARTIFACT_BUCKET→semgrep_artifact_bucket, SEMGREP_PREFIX→semgrep_artifact_prefix)`. |
| `tool_source_label` | string | yes | `{source}` | `scripts/install.sh` verify-step `WHERE tool_source='<label>'`. |
| `entry_wrappers` | bool | yes | `true` (sonarqube) / `false` (semgrep) | sonarqube has `ingest_entry.py` + `transform_entry.py`; semgrep does not (job points at `../ingest.py`). Driven by whether the connector needs a notebook-shaped widget+secret-fetch wrapper. |
| `bronze_volume` | string | yes (cli only) | `{source}_artifacts` | `resources/volumes.yml` `volumes.{volume_key}.name`. semgrep=`semgrep_artifacts`. CLI-artefact path uses Auto Loader on a UC Volume. |
| `bronze_volume_storage_location` | string | yes (cli only) | `s3://${var.artifact_bucket}/{source}/` | `resources/volumes.yml` `storage_location`. semgrep=`s3://${var.artifact_bucket}/semgrep/`. |
| `cli_artefact_prefixes` | list[string] | yes (cli only) | (none) | `config.yml` `prefixes:`. semgrep=`[periodic/semgrep/, cicd/semgrep/]`. Where the CLI artefacts land within the bucket. |
| `extra_install_env_vars` | list[string] | no | (none) | `scripts/install.sh` extra `: "${VAR:?...}"`. sonarqube adds `SONARQUBE_HOST` (alias for SONARQUBE_URL) and `SONARQUBE_ORG`. |

16 fields (12 always-required + 4 cli-only).

**Judgment call:** `entry_wrappers` is SONARQUBE_ONLY in current state. Generate-connector should emit them for any server-based SAST source where credential fetching from secrets is needed at notebook startup. Semgrep (CLI-artefact) reads from a Volume via Auto Loader and does not need them.

## Databricks-side production-shape

### scripts/load-secrets.sh template

Same iterate-over-secret-env-vars shape as CMDB/SCM. For CLI-artefact SAST, the "secrets" are artefact-bucket pointers + optional AWS credentials, not API tokens.

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
{% if databricks_runtime.deployment_style == "cli_artefact" %}
# {{ source }} doesn't expose an API — the connector reads JSON findings
# from an object-storage prefix that the {{ source }} runner writes to.
{% endif %}
#
# Reads from environment variables:
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}
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

Same notebook-job-trigger shape as SCM. SAST verify-step asserts `silver.findings WHERE tool_source = '<label>'`.

```bash
#!/usr/bin/env bash
# install.sh — end-to-end installer for the {{ source }} connector.
# (See SCM template — same shape; verify-step queries silver.findings WHERE tool_source.)

set -euo pipefail
{% for entry in databricks_runtime.secret_env_vars %}
: "${{ '{' }}{{ entry.env_var }}:?{{ entry.env_var }} is required{{ '}' }}"
{% endfor %}
{% for v in databricks_runtime.extra_install_env_vars %}
: "${{ '{' }}{{ v }}:?{{ v }} is required{{ '}' }}"
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
  echo "  To verify by hand:"
{% for tbl in databricks_runtime.bronze_tables %}
  echo "    SELECT count(*) FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};"
{% endfor %}
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}';"
else
{% for tbl in databricks_runtime.bronze_tables %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }}"
{% endfor %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}'"
fi

echo "OK: {{ source }} connector install complete."
```

### install.sh (top-level) template

Same chain shape as SCM/CMDB. SAST source-side runtime varies by deployment style: server-based uses `hashicorp/kubernetes` (Helm chart for SonarQube); CLI-artefact uses `hashicorp/kubernetes` (EKS CronJob for Semgrep) or `hashicorp/aws` (S3 bucket for artefact landing).

### *_entry.py applicability

**APPLICABLE for server-based SAST** (`databricks_runtime.entry_wrappers=true`); use the generic SCM-shaped template (widgets + dbutils.secrets fetch + delegation to `src.connectors.{{ source }}.{ingest,transform}`). The current sonarqube wrappers are SCAFFOLDING ONLY (`print("sonarqube ingest_entry — scaffolding")`); generate-connector must EMIT functional wrappers, not the scaffolding shape.

**N/A for cli_artefact SAST.** Auto Loader on a UC Volume is the ingest path; `resources/job.yml` points directly at `../ingest.py`. The semgrep follower correctly omits `*_entry.py`.

### sql/<envelope>.sql template

**N/A for SAST.** Neither sonarqube nor semgrep emit a `sql/` directory — bronze tables are populated directly by `ingest.py` (server) or Auto Loader (CLI). The framework metadata columns are projected inline.

### resources/extras (per category)

Server-based SAST (sonarqube shape) emits:
- `resources/job.yml` (8-file core) with `notebook_path: ../ingest_entry.py` / `../transform_entry.py`.
- `resources/schemas.yml` — `bronze_{source}` only:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
  ```

- `resources/connection.yml` — **N/A** (PAT auth via dbutils.secrets, not UC connection).
- `resources/pipeline.yml` — **N/A** (notebook-job pattern, not Lakeflow Connect).
- `resources/volumes.yml` — **N/A**.

CLI-artefact SAST (semgrep shape) emits:
- `resources/job.yml` (8-file core) with `notebook_path: ../ingest.py` / `../transform.py` (no entry wrappers).
- `resources/schemas.yml` — `bronze_{source}` only.
- `resources/volumes.yml` — REQUIRED. UC Volume backing the artefact prefix:

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

- `resources/connection.yml` — **N/A**.
- `resources/pipeline.yml` — **N/A**.

### Page §4–§7 templates

#### §Secrets (page §4)

```markdown
## Secrets

Loaded into the `{{ databricks_runtime.secret_scope }}` secret scope by `src/connectors/{{ source }}/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
{% for entry in databricks_runtime.secret_env_vars %}
| `{{ entry.secret_key }}` | `{{ entry.env_var }}` | <purpose from page §3> |
{% endfor %}

Run from repo root after Phase 1 completes:

```bash
{% for entry in databricks_runtime.secret_env_vars %}
export {{ entry.env_var }}="..."
{% endfor %}
{% for v in databricks_runtime.extra_install_env_vars %}
export {{ v }}="..."
{% endfor %}
bash src/connectors/{{ source }}/scripts/load-secrets.sh
# Expected: OK: {{ source }} secrets loaded into scope {{ databricks_runtime.secret_scope }}
```
```

#### §Run the job (page §5)

```markdown
## Run the job

{% if databricks_runtime.deployment_style == "cli_artefact" %}
Before the connector ingests anything, the {{ source }} runner must drop `--json` artefacts under the configured prefix(es) ({{ databricks_runtime.cli_artefact_prefixes | join(", ") }}). The connector reads them autoloader-style.
{% else %}
Before the connector ingests anything, the {{ source }} server must have analysis results to expose. Run a scanner against your target repos (see source documentation).
{% endif %}

Then trigger the Databricks job:

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a one-shot orchestration:

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```

The job is declared in `src/connectors/{{ source }}/resources/job.yml` (job key `{{ databricks_runtime.job_name }}`) and runs on the configured cron once enabled.
```

#### §Verify (page §6)

```markdown
## Verify

```sql
{% for tbl in databricks_runtime.bronze_tables %}
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};
{% endfor %}

SELECT severity_canonical, count(*)
  FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}'
  GROUP BY severity_canonical;
```

Expected: bronze rows for each scan; silver rows discriminated by `tool_source`. Severity distribution should follow `src/connectors/{{ source }}/severity.yml`.
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` from the Databricks job | Token expired or wrong permissions. Generate a new token, re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh`, re-trigger the job. |
| 0 rows in `{{ databricks_runtime.bronze_tables[0] }}` | {% if databricks_runtime.deployment_style == "cli_artefact" %}No artefacts have landed under the configured prefix. Verify with object-storage `ls`.{% else %}The source has no analysis results yet, or filters excluded all records.{% endif %} |
| Validation table shows `REQ-DEDUP` FAIL | Cross-tool dedup against another SAST source depends on overlap. Run multiple SAST connectors against the same repo set first. |
{% if databricks_runtime.deployment_style == "cli_artefact" %}
| Auto Loader not picking up new artefacts | UC Volume `{{ databricks_runtime.bronze_volume }}` may not have read access to `{{ databricks_runtime.bronze_volume_storage_location }}`. Check the workspace's AWS service credential. |
{% endif %}
```

## Ingestion-path branch: sdk

> **Status: aspirational.** No source in this category currently uses the sdk branch; templates here cover dlt and artifact_path only. SonarQube is on `dlt` (no actively-maintained generic SDK), Semgrep CI is on `artifact_path`, and Semgrep AppSec Platform falls through to `dlt`. When a future SAST source enters the analyze-source Maintained Python SDK catalogue, this section will gain the per-SDK template (mirroring `references/scm.md` "## Ingestion-path branch: sdk").
