# generate-connector — SCM reference

Facts the generate-connector skill needs to emit an SCM connector module. SCM sources are dual-role: entities (always) plus platform-native findings (where the platform hosts native scanners — Dependabot, code scanning, secret scanning).

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

- Always bind (entity role): `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-TS`, `REQ-DQ`.
- Bind only when the SCM source is configured as a finding-emitting integration (platform-native scanners — Dependabot, code scanning, secret scanning): `REQ-TRF-SEV`, `REQ-TRF-STS`, `REQ-DEDUP`.
- Pure-entity SCM connectors (no platform-native findings consumed) MUST NOT bind the three finding-only REQ-IDs.

## Default severity

For the entity role: N/A — entity rows have no `severity` column.

For the finding role: derived from the platform's native field (`rule.security_severity_level` for GitHub code scanning, `severity` for GitLab) and normalized via `config/severity/{source}.yml` to the canonical four-level model (`critical`, `high`, `medium`, `low`). Configurable default for unmatched values is `medium`. The lookup file MUST cover every source value documented in the connector page.

## Incremental strategy

Three-option preference order; encode the chosen option in `config.yml`:

1. **Webhook / event-stream** (preferred where exposed). The connector materialises events into Bronze in near-real-time. Emit subscription configuration, not polling.
2. **Native `updated_at` (or equivalent) column** as the high-water mark, persisted via `src/common/` HWM helpers.
3. **Full reload**, reserved for sources exposing neither.

The selected mode MUST match the connector page's Incremental hook fact.

## Deduplication key

For the entity role: not applicable. Entity dedup uses the natural-key column at Bronze-to-Silver upsert; no `dedup_links` rows are emitted.

For the finding role: encode the dedup-key tuple by finding shape (the source typically emits multiple shapes simultaneously):

- Code scanning (SAST shape): `(repository_id, file_path, rule_id)`.
- Secret scanning (secrets shape): `(repository_id, commit_sha, secret_type, file_path)`.
- Dependabot (SCA shape): `(repository_id, package_name, cve_id)`.

`transform.py` MUST branch on the finding-shape discriminator (the connector reads which scanner produced the row) and emit `dedup_links` rows keyed by the matching tuple. The Quirks section of the connector page identifies which shapes the source emits.

## Target Silver tables

Authoritative names per `mkdocs/docs/platform/reference/silver-table-ownership.md`:

- Entity role: `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. (`silver.commits` and `silver.teams` may also be populated where the source exposes them.)
- Finding role: `silver.findings` (single union table) discriminated by `category` per the matching scanner shape (`sast`, `sca`, `secrets`).

The `mapping.yml` file MUST contain TWO top-level blocks when the source emits both entities and findings:

```yaml
entities:
  # repository, pull_request, branch_policy field projections
findings:
  # platform-native finding field projections, discriminated by category
```

Pure-entity sources omit the `findings` block.

## Authentication norms

Personal access token (PAT) or OAuth. `ingest.py` reads credentials via `src/common/` from the secret scope; `config.yml` references the secret-scope key names only. For OAuth deployments, encode the token-refresh callback in the helper, not inline.

## Ingestion-tooling preference

Per the standard order with one practical split:

- **Entities**: Lakeflow Connect first where a managed GitHub / GitLab connector exists; SDK / dlt fall back otherwise.
- **Findings**: Databricks SDK is the preferred path — GitHub and GitLab finding APIs (Dependabot alerts, code scanning alerts, secret scanning alerts) are SDK-covered and require finer pagination control than Lakeflow Connect typically exposes.

Justify the chosen tool with a one-line comment at the top of `ingest.py`.

## Quirks

- **Two `mapping.yml` blocks.** A single SCM source typically populates entity tables AND `silver.findings`. Emit two clearly delimited blocks; do NOT collapse them. Pure-entity sources emit only the entity block.
- **Plural Silver names are authoritative.** `silver.repositories`, `silver.pull_requests`, `silver.branch_policies`. Singular forms are wrong.
- **Cursor vs keyset pagination.** GraphQL APIs typically use cursor pagination; REST APIs may use keyset. Encode the pagination strategy per endpoint in `config.yml`; `src/common/` exposes both helpers.
- **Webhook replay.** When webhook delivery is the chosen incremental hook, `config.yml` MUST also encode a fallback polling window (typically 24h) so missed deliveries are recovered on the next scheduled run.
- **Finding-shape branch.** `transform.py` MUST handle each shape (code-scanning, secret-scanning, Dependabot) with the matching dedup-key tuple. Mis-branching corrupts `dedup_links`.

## operational.yml.databricks_runtime schema

Reverse-engineered from `src/connectors/gitlab/...` (live follower) and cross-checked against `git show a086f9d:src/connectors/github/...` (original).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` line `SCOPE="mvp-connectors"`; `scripts/install.sh` "Loading … into the {{ secret_scope }} scope". |
| `bronze_schema` | string | yes | `bronze_{source}` | `git show a086f9d:src/connectors/github/resources/schemas.yml` `name: bronze_github`; `gitlab/resources/schemas.yml` `name: bronze_gitlab`. |
| `silver_schema` | string | no | `silver_{source}` | `git show a086f9d:src/connectors/github/resources/schemas.yml` second entry `silver_github` — emitted only when the SCM source carries a per-source silver namespace; gitlab does not emit one. |
| `bronze_tables` | list[string] | yes | (none) | `scripts/install.sh` verify-step queries `${CATALOG}.bronze_{source}.<table>` (gitlab: `projects`; github: `repositories`); `transform_entry.py` `bronze_table = f"{target_catalog}.bronze_{source}.<table>"`. |
| `cron_schedule` | string | yes | `0 */15 * * * ?` (every 15 min) | `resources/job.yml` `quartz_cron_expression`. gitlab uses 15-min, github (a086f9d) uses 3-hour `0 0 */3 * * ?`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/schemas.yml` `catalog_name: ${var.catalog}`. |
| `job_name` | string | yes | `{source}-connector` (kebab) | `resources/job.yml` `jobs.{job_name}`; `scripts/install.sh` `databricks bundle run {{ job_name }}`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `TARGET="${DATABRICKS_TARGET:-dev}"`. |
| `default_catalog` | string | no | `appsec_dev` | `scripts/install.sh` `CATALOG="${CATALOG:-appsec_dev}"`. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` `databricks secrets put-secret …` lines. gitlab: `(GITLAB_BASE_URL→gitlab_base_url, GITLAB_TOKEN→gitlab_token)`. github: `(GITHUB_PAT→github_token, GITHUB_ORG→github_org)`. |
| `extra_install_env_vars` | list[string] | no | (none) | `scripts/install.sh` extra `: "${VAR:?...}"` checks beyond `load-secrets.sh` env vars. gitlab adds `GITLAB_GROUP_ID` (job-parameter, not a secret). |
| `tool_source_label` | string | yes | `{source}` | `scripts/install.sh` verify-step `WHERE tool_source='{{ tool_source_label }}'` (gitlab uses `'gitlab'`; github uses `'github'`). |
| `entry_wrappers` | bool | yes | `true` (SCM) | a086f9d `github/{ingest,transform}_entry.py` exist; `resources/job.yml` `notebook_path: ../ingest_entry.py`. **Decision:** SCM emits entry wrappers because of credential-fetching from secrets at notebook startup. gitlab is currently MISSING entry wrappers (template gap) — generate-connector should emit them on re-emit. |
| `webhook_endpoint_url` | string | no | (none) | Connector page §3 Reference "Incremental hook"; `config.yml` webhook block when webhook-preferred mode applies. Gitlab/github currently encode this in `config.yml` only, not bundle resources. |

13 fields.

**Judgment call:** `entry_wrappers=true` is the SCM canonical shape (github a086f9d state) but the gitlab follower omits them. On re-emit the skill should EMIT entry wrappers for both sources; this is a template gap that closes on Phase 2 follower re-emit, not a regression.

## Databricks-side production-shape

What `generate-connector` emits for the SCM category.

### scripts/load-secrets.sh template

Same shape as CMDB. Iterates over `databricks_runtime.secret_env_vars`. Example for gitlab: writes `gitlab_base_url` from `GITLAB_BASE_URL` and `gitlab_token` from `GITLAB_TOKEN`.

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
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

SCM-specific shape: triggers a **notebook job** (not a Lakeflow pipeline) via `databricks bundle run`. Verifies bronze + silver counts including `tool_source` discriminator.

```bash
#!/usr/bin/env bash
# install.sh — end-to-end installer for the {{ source }} connector.
#
# Wraps the three steps a fresh operator runs to take an empty Databricks
# workspace + an existing {{ source }} group from zero to populated bronze + silver
# rows in `{{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.*` and
# `{{ databricks_runtime.default_catalog }}.silver.{repositories,findings}`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `{{ databricks_runtime.secret_scope }}` secret scope,
#     and the `silver` schema exist; `databricks bundle deploy --target {{ databricks_runtime.default_target }}`
#     has been run from repo root at least once so the `{{ databricks_runtime.bronze_schema }}` schema
#     and the `{{ databricks_runtime.job_name }}` job are registered).
#   - Databricks CLI authenticated.
#
# Required env vars
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}
{% endfor %}
{% for v in databricks_runtime.extra_install_env_vars %}
#   {{ v }}
{% endfor %}
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "{{ databricks_runtime.default_target }}".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query.
#   CATALOG           — Unity Catalog name. Defaults to "{{ databricks_runtime.default_catalog }}".

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

echo "Step 1/3: Loading {{ source }} secrets into the {{ databricks_runtime.secret_scope }} scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the {{ databricks_runtime.job_name }} job (target=${TARGET})..."
databricks bundle run {{ databricks_runtime.job_name }} --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
{% for tbl in databricks_runtime.bronze_tables %}
  echo "    SELECT count(*) FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};"
{% endfor %}
  echo "    SELECT count(*) FROM ${CATALOG}.silver.repositories WHERE source='{{ databricks_runtime.tool_source_label }}';"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}';"
else
{% for tbl in databricks_runtime.bronze_tables %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_{{ tbl }} FROM ${CATALOG}.{{ databricks_runtime.bronze_schema }}.{{ tbl }}"
{% endfor %}
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repos FROM ${CATALOG}.silver.repositories WHERE source='{{ databricks_runtime.tool_source_label }}'"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='{{ databricks_runtime.tool_source_label }}'"
fi

echo "OK: {{ source }} connector install complete."
```

### install.sh (top-level) template

Same chain shape as CMDB. SCM source-side runtime is typically the `hashicorp/github` or `hashicorp/gitlab` provider for repo + webhook setup; `runtime/install.sh` runs `terraform apply` against that.

```bash
#!/usr/bin/env bash
# Top-level orchestrator for the {{ source }} connector.
# Chain: runtime/install.sh → scripts/load-secrets.sh → databricks bundle deploy.
# Pass --skip-runtime when the SCM platform is already provisioned.
set -euo pipefail
SKIP_RUNTIME=0
for arg in "$@"; do case "$arg" in --skip-runtime) SKIP_RUNTIME=1 ;; esac; done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
if [[ "$SKIP_RUNTIME" -eq 0 && -x "${SCRIPT_DIR}/runtime/install.sh" ]]; then
  echo "Step 1/3: Provisioning source runtime..."; bash "${SCRIPT_DIR}/runtime/install.sh"
else
  echo "Step 1/3: Skipping source runtime."
fi
echo "Step 2/3: Loading secrets..."; bash "${SCRIPT_DIR}/scripts/load-secrets.sh"
echo "Step 3/3: Deploying bundle..."; databricks bundle deploy --target "${DATABRICKS_TARGET:-{{ databricks_runtime.default_target }}}"
echo "OK: {{ source }} connector installed."
```

### *_entry.py applicability

**APPLICABLE for SCM** when `databricks_runtime.entry_wrappers=true`. Reverse-engineered from `git show a086f9d:src/connectors/github/{ingest,transform}_entry.py`. Notebook-shaped Python files with `# Databricks notebook source` header; thin dispatchers that read `dbutils.widgets`, fetch credentials from `dbutils.secrets`, and delegate to `src.connectors.{{ source }}.{ingest,transform}.{ingest,transform}`.

#### ingest_entry.py template

```python
# Databricks notebook source
"""Databricks entry point for the {{ source }} ingest task.

Thin dispatcher: reads the three DAB job parameters (source_name,
target_catalog, hwm_reset) via dbutils widgets, resolves the Databricks
job_run_id from the notebook context, loads the connector state, and
calls src.connectors.{{ source }}.ingest.ingest(run_id, state).

The transform task is a separate notebook (transform_entry.py) wired in
src/connectors/{{ source }}/resources/job.yml with depends_on: ingest per
thesis section 2.4.2.
"""

from src.connectors.{{ source }}.ingest import ingest

# COMMAND ----------

dbutils.widgets.text("source_name", "{{ source }}")
dbutils.widgets.text("target_catalog", "")
dbutils.widgets.text("hwm_reset", "false")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")
hwm_reset = dbutils.widgets.get("hwm_reset").lower() == "true"

# COMMAND ----------

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
run_id = ctx.tags().apply("runId") if "runId" in ctx.tags().keySet() else ctx.jobId().get()

# COMMAND ----------

state = {
    "source": source_name,
    "hwm_value": None if hwm_reset else None,
    "extra": {
{% for entry in databricks_runtime.secret_env_vars %}
        "{{ entry.secret_key }}": dbutils.secrets.get(scope="{{ databricks_runtime.secret_scope }}", key="{{ entry.secret_key }}"),
{% endfor %}
        "catalog": target_catalog,
    },
}

# COMMAND ----------

descriptor = ingest(run_id=str(run_id), state=state)
print(descriptor)
```

#### transform_entry.py template

```python
# Databricks notebook source
"""Databricks entry point for the {{ source }} transform task."""

from pyspark.sql import SparkSession

from src.connectors.{{ source }}.transform import transform

# COMMAND ----------

dbutils.widgets.text("source_name", "{{ source }}")
dbutils.widgets.text("target_catalog", "")
dbutils.widgets.text("hwm_reset", "false")

source_name = dbutils.widgets.get("source_name")
target_catalog = dbutils.widgets.get("target_catalog")

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()
bronze_table = f"{target_catalog}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.bronze_tables[0] }}"
bronze_df = spark.read.table(bronze_table)

# COMMAND ----------

silver_df = transform(bronze_df)
print(silver_df.count())
```

### sql/<envelope>.sql template

**N/A for SCM.** The SCM bronze tables are populated by the connector's `ingest.py` directly (not Lakeflow Connect overlay), so no envelope-VIEW overlay is needed. The framework `_envelope` columns are projected inline in `ingest.py` writes. Neither gitlab nor github (a086f9d) emit a `sql/` directory.

### resources/extras (per category)

SCM emits `resources/job.yml` (8-file core) PLUS:

- `resources/schemas.yml` — at minimum `bronze_{source}`. Some SCM sources (github a086f9d) ALSO emit `silver_{source}` for per-source-silver use; SCM-as-finding-source uses the shared `silver` schema (created by platform bootstrap), so `silver_{source}` is optional and emitted only when `databricks_runtime.silver_schema` is set:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
  {% if databricks_runtime.silver_schema %}
      {{ databricks_runtime.silver_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.silver_schema }}
  {% endif %}
  ```

- `resources/connection.yml` — **N/A for SCM.** SCM connectors authenticate via PAT through `dbutils.secrets`, not via a UC connection.
- `resources/pipeline.yml` — **N/A for SCM.** SCM uses the notebook-job pattern from `resources/job.yml`, not Lakeflow Connect.
- `resources/volumes.yml` — **N/A for SCM.** No artefact bucket; ingest writes directly to bronze tables.

`resources/job.yml` (8-file core) for SCM has `notebook_path: ../ingest_entry.py` / `../transform_entry.py` when `entry_wrappers=true`, otherwise `../ingest.py` / `../transform.py`. `quartz_cron_expression` matches `databricks_runtime.cron_schedule`.

### Page §4–§7 templates

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

```markdown
## Run the job

The {{ source }} ingestion is a notebook job named `{{ databricks_runtime.job_name }}` (declared in `src/connectors/{{ source }}/resources/job.yml`) that runs on the configured cron once enabled. Trigger an on-demand run:

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a one-shot orchestration (load secrets + run + verify counts):

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```

The job has two tasks: `ingest` (REST → Bronze) and `transform` (Bronze → `silver.repositories` + `silver.findings`).
```

#### §Verify (page §6)

```markdown
## Verify

```sql
-- Bronze: raw entities/findings landed by the ingest task.
{% for tbl in databricks_runtime.bronze_tables %}
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ tbl }};
{% endfor %}

-- Silver entities and findings discriminated by source.
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.silver.repositories
  WHERE source = '{{ databricks_runtime.tool_source_label }}';
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}';
```

Expected: bronze rows for each entity/finding shape; silver rows discriminated by `source` (entities) and `tool_source` (findings).
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` from the {{ databricks_runtime.job_name }} job | Token expired or wrong scope. Generate a new PAT, re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh` with the new token exported, and re-trigger the job. |
| 0 rows in `{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.bronze_tables[0] }}` | The token's scope does not cover the configured org/group, OR no entities exist in the org. Verify with `curl -H "Authorization: bearer $TOKEN" <api-url>` directly. |
| Validation table shows `REQ-DEDUP` FAIL | Cross-tool dedup depends on multiple finding-emitting connectors having ingested the same repository. Run other connectors against the same SCM org first. |
| No rows in `silver.repositories` | The transform task did not run, or `silver` schema bootstrap was skipped. Re-run the bundle deploy. |
```
