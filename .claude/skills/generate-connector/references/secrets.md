# generate-connector — Secrets reference

> **Ingestion path:** all sources in this category resolve to `sdk_dlt` (or `artifact_path` per the category quirks documented below). The `lakeflow_connect` branch is documented in `cmdb.md`; templates here cover the non-LFC branches only. CLI-tool sources (Semgrep / TruffleHog / OWASP ZAP CLI) resolve to `artifact_path`; server-based sources (SonarQube / Snyk / OWASP ZAP daemon) resolve to `sdk_dlt`.

Facts the generate-connector skill needs to emit a secret-detection connector module. Secrets sources emit findings with reduced lifecycle metadata.

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

- Bind: `REQ-ING-HWM` (full-reload still has an HWM in the form of commit SHA / scan-start timestamp), `REQ-TRF-MAP`, `REQ-TRF-SEV` (degraded — see Default severity), `REQ-TRF-TS`, `REQ-DQ`, `REQ-DEDUP`.
- Do NOT bind `REQ-TRF-STS` — secret-detection sources do not expose a status / lifecycle vocabulary. The generated `transform.py` MUST NOT include status-transition logic.
- For CLI-based scanners (TruffleHog artefacts — the dominant deployment style), `REQ-ING-AUTH`, `REQ-ING-PAG`, `REQ-ING-RL` are N/A per the catalog. Do NOT bind these three.

## Default severity

`high`, hard-coded. The `mapping.yml` finding block sets severity to a literal `high` constant — it does NOT reference a lookup-driven source field (this is the documented degraded form):

```yaml
severity:
  literal: high
```

The `config/severity/{source}.yml` file MUST still exist (every connector has both lookup files per the framework contract) and contain a single comment line:

```
# default high; per-deployment override permitted for low-entropy detector classes
```

The lookup is consulted only when an operator deploys a per-detector override; the default code path uses the literal `high` from `mapping.yml`.

## Incremental strategy

Full-reload only. Encode in `config.yml`:

- HWM is the commit SHA (CI/CD-step deployments — every commit is a potential leak) or the scan-start timestamp (periodic-global host-side scans like GitHub Secret Scanning).
- No record-level update column — the source has none.
- The HWM advances on each full pull; replays of historical scans re-emit the same `(repository_id, commit_sha)` rows for dedup-time unification.

## Deduplication key

The dedup tuple `(repository_id, commit_sha, secret_type, file_path)` matches the Secrets capability surface at [`mkdocs/docs/connectors/secrets/index.md`](../../../../mkdocs/docs/connectors/secrets/index.md) § "Canonical mapping contribution" and is consistent with the canonical Silver Finding shape at [`mkdocs/docs/platform/reference/canonical-mapping.md`](../../../../mkdocs/docs/platform/reference/canonical-mapping.md#silver-finding-mapping-requirements). Encode this tuple literally in `transform.py`:

```python
dedup_key = (row["repository_id"], row["commit_sha"], row["secret_type"], row["file_path"])
```

Both per-commit (CI/CD-step) and host-side periodic-global secret scanning emit records labelled with `(repository_id, commit_sha)` — Bronze-to-Silver dedup unifies them on the four-tuple without double-counting.

## Target Silver tables

`silver.findings` discriminated by `category="secrets"` per `mkdocs/docs/platform/reference/silver-table-ownership.md`. The `mapping.yml` finding block MUST set `category: "secrets"` literally and project the secret-specific fields:

- `secret_type` — the detector class label (TruffleHog `DetectorName`).
- `validity_status` — derived from the source's verification flag where present (TruffleHog `Verified` + `VerificationError`); null where the source does not verify.

The status field is NOT projected — secrets emit no lifecycle.

## Authentication norms

- **CLI-based** (the dominant style — TruffleHog, gitleaks): no API auth. Access is governed by the artefact bucket's IAM policy. `config.yml` encodes the bucket prefix; `ingest.py` uses the autoloader / cloud-storage helpers in `src/common/`.
- **Server-based** (rare): PAT or API-key, as for SAST. `ingest.py` reads credentials via the helper in `src/common/`.

The connector page identifies which path the source takes; emit the matching auth code (or its absence).

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **CLI-based secret scanners are the documented exception** (alongside Semgrep Docker per `CLAUDE.md`). Emit a CLI-artefact ingest path — autoloader-style on the object-storage prefix, or `httpx` against a cloud-storage API. Justify the deviation in a top-of-file comment in `ingest.py`.
- Server-based scanners use the SDK or dlt path.

## Quirks

- **`Raw` and `RawV2` MUST NOT enter Silver.** For TruffleHog and similar scanners, drop the raw secret value before Bronze-to-Silver — keep only `Redacted`. This is mandatory, not configurable. Encode the projection in `mapping.yml` to exclude raw fields explicitly; an optional Unity Catalog column-level access policy on Bronze is the deployment-time enforcement.
- **Verification semantics.** Where the source supports live credential verification, populate `validity_status` from the verification flag in `mapping.yml`. Document the source field name (e.g. `Verified` for TruffleHog) in a transform-level comment.
- **No status transitions.** `REQ-TRF-STS` is N/A; do not generate status-transition code or status-lookup references. The Silver `status` field is left null (or set to `open` on first emit) — encode the constant in `mapping.yml`, NOT a lookup.
- **CI/CD-step dominance.** Secret detection is almost exclusively CI/CD-step in practice; the `config.yml` HWM shape is the commit SHA. Periodic-global host-side scans (GitHub Secret Scanning) use scan-start timestamp; both shapes co-exist on the four-tuple dedup key.
- **Detector-class severity overrides.** The optional `config/severity/{source}.yml` deployment override may downgrade specific detector classes (low-entropy patterns, deprecated detectors) below the default `high`. The override path is opt-in; the default code path uses the `mapping.yml` literal.

## operational.yml.databricks_runtime schema

Reverse-engineered from `src/connectors/trufflehog/...` (live follower; CLI-artefact secrets).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` `SCOPE="mvp-connectors"`; `config.yml` `bucket_secret_scope: mvp-connectors`. |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name: bronze_trufflehog`; `sql/artefact_envelope.sql` `${catalog}.bronze_trufflehog.findings`. |
| `bronze_tables` | list[string] | yes | (none) | `config.yml` `bronze_table: ${catalog}.bronze_trufflehog.findings`. |
| `envelope_table` | string | yes | `findings` | `sql/artefact_envelope.sql` `CREATE TABLE … bronze_trufflehog.findings`. Note: secrets envelope IS the bronze table (CREATE TABLE; not a VIEW overlay). |
| `cron_schedule` | string | yes | `0 0 * * * ?` (hourly) | `resources/job.yml` `quartz_cron_expression`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/schemas.yml` `catalog_name`. |
| `job_name` | string | yes | `{source}-connector` (kebab) | `resources/job.yml` `jobs.{job_name}`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `--target dev`. |
| `default_catalog` | string | no | `appsec_dev` | (not currently used in trufflehog install.sh — value implicit). |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` put-secret lines. trufflehog: `(TRUFFLEHOG_ARTIFACT_BUCKET→trufflehog_artifact_bucket)`, plus a CONDITIONAL `(AWS_ACCESS_KEY_ID+AWS_SECRET_ACCESS_KEY→trufflehog_aws_credentials)` JSON-encoded blob. |
| `optional_aws_credentials_secret` | bool | yes | `true` | `scripts/load-secrets.sh` conditional block: writes `trufflehog_aws_credentials` JSON only when `AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY` are exported (S3 path); skipped on UC Volume mode. |
| `tool_source_label` | string | yes | `{source}` | Verify-step assumption — silver.findings `tool_source` discriminator. |
| `entry_wrappers` | bool | yes | `false` | trufflehog `resources/job.yml` `notebook_path: ../ingest.py` (no entry wrappers). Auto Loader on the artefact path runs in-notebook. |
| `cli_artefact_prefixes` | list[string] | yes | `[trufflehog/]` | `config.yml` `prefixes:`. trufflehog=`[trufflehog/]`. |
| `bronze_volume` | string | no | (none) | trufflehog does NOT currently emit `resources/volumes.yml` (uses bucket-secret-pointer instead of declarative UC Volume). Optional for sources that prefer UC Volume Auto Loader. |

15 fields.

**Judgment call:** `optional_aws_credentials_secret` is trufflehog-specific — the CLI-artefact path supports BOTH S3 (needs creds) and UC Volume (no creds, Databricks-internal IAM). Generate-connector emits a conditional block in `load-secrets.sh` driven by this flag.

## Databricks-side production-shape

### scripts/load-secrets.sh template

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
#
# {{ source }} is a CLI-artefact connector: scans run on CI/CD runners and
# write `--json` line-delimited output to a Databricks Volume or S3 bucket.
# The connector reads from that location autoloader-style.
#
# Reads from environment variables:
{% for entry in databricks_runtime.secret_env_vars %}
#   {{ entry.env_var }}
{% endfor %}
{% if databricks_runtime.optional_aws_credentials_secret %}
#   AWS_ACCESS_KEY_ID          — optional (S3 path only)
#   AWS_SECRET_ACCESS_KEY      — optional (S3 path only)
{% endif %}
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

{% if databricks_runtime.optional_aws_credentials_secret %}
if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  CREDS=$(printf '{"access_key_id":"%s","secret_access_key":"%s"}' "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")
  databricks secrets put-secret "$SCOPE" {{ source }}_aws_credentials --string-value "$CREDS"
  echo "OK: {{ source }} secrets loaded into scope $SCOPE (incl. AWS credentials)"
else
  echo "OK: {{ source }} secrets loaded into scope $SCOPE (no AWS credentials; UC Volume mode)"
fi
{% else %}
echo "OK: {{ source }} secrets loaded into scope $SCOPE"
{% endif %}
```

### scripts/install.sh template

Minimal three-step shape (load-secrets → bundle run → echo verify).

```bash
#!/usr/bin/env bash
# End-to-end {{ source }} connector install orchestrator.
#
# Pre-conditions:
#   - Phase 1 platform bootstrap is complete (catalog, {{ databricks_runtime.secret_scope }} scope, silver schema).
#   - At least one SCM connector has been installed and run so silver.repositories is populated.
#   - {{ databricks_runtime.secret_env_vars[0].env_var }} is exported (artefact location).
#   - At least one {{ source }} `--json` artefact is dropped at the configured location.
set -euo pipefail

echo "Step 1/3: Loading secrets..."
bash src/connectors/{{ source }}/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run {{ databricks_runtime.job_name }} --target {{ databricks_runtime.default_target }}
echo "Step 3/3: Run verification SQL — see runbook"
echo "OK: {{ source | title }} connector install complete."
```

### install.sh (top-level) template

Same chain as other categories. Secrets source-side runtime is typically `hashicorp/aws` (S3 bucket / UC Volume) + `hashicorp/kubernetes` (CronJob).

### *_entry.py applicability

**N/A for secrets.** CLI-artefact path uses Auto Loader on the artefact prefix; ingest runs in-notebook from `ingest.py`. Generate-connector emits no `*_entry.py` for secrets sources.

### sql/<envelope>.sql template

REQUIRED. CREATE TABLE shape (the bronze table itself; Auto Loader writes raw JSON envelopes here).

```sql
-- Bronze envelope for {{ source }} scan artefacts.
--
-- Autoloader reads line-delimited JSON files from the UC Volume
-- (`<catalog>.{{ databricks_runtime.bronze_schema }}.artefacts`) and lands them here.
-- The secrets transform (`src/connectors/{{ source }}/transform.py`) projects
-- this table into silver.findings, dropping the `Raw` / `RawV2` fields
-- per the references/secrets.md redaction rule.
--
-- The table name `{{ databricks_runtime.envelope_table }}` matches the `bronze_table` configured in
-- `src/connectors/{{ source }}/config.yml` and the literal default in
-- `ingest.run_ingest_pipeline` — keep all three in sync if renamed.

CREATE TABLE IF NOT EXISTS {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }} (
  raw_payload STRING,
  artefact_path STRING,
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT '{{ source | title }} scan JSON; transformed into silver.findings (secrets).';
```

### resources/extras (per category)

- `resources/job.yml` (8-file core) with `notebook_path: ../ingest.py` / `../transform.py`. Hourly cron.
- `resources/schemas.yml` — `bronze_{source}` only.
- `resources/connection.yml` — **N/A** (no API auth).
- `resources/pipeline.yml` — **N/A** (notebook job, not Lakeflow Connect).
- `resources/volumes.yml` — OPTIONAL. Emit when `databricks_runtime.bronze_volume` is set. Trufflehog currently does NOT emit one (pointer-based via secret scope); peer CLI-artefact connectors (semgrep) DO emit one. Template:

  ```yaml
  resources:
    volumes:
      {{ databricks_runtime.bronze_volume }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        schema_name: {{ databricks_runtime.bronze_schema }}
        name: {{ databricks_runtime.bronze_volume }}
        volume_type: EXTERNAL
        storage_location: s3://${var.artifact_bucket}/{{ source }}/
  ```

### Page §4–§7 templates

#### §Secrets (page §4)

```markdown
## Secrets

Loaded into the `{{ databricks_runtime.secret_scope }}` secret scope by `src/connectors/{{ source }}/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
{% for entry in databricks_runtime.secret_env_vars %}
| `{{ entry.secret_key }}` | `{{ entry.env_var }}` | Artefact location pointer or {{ source }}-specific config. |
{% endfor %}
{% if databricks_runtime.optional_aws_credentials_secret %}
| `{{ source }}_aws_credentials` | `AWS_ACCESS_KEY_ID`+`AWS_SECRET_ACCESS_KEY` (optional) | JSON blob; skipped on UC Volume mode. |
{% endif %}

```bash
{% for entry in databricks_runtime.secret_env_vars %}
export {{ entry.env_var }}="..."
{% endfor %}
{% if databricks_runtime.optional_aws_credentials_secret %}
# Optional — skip on UC Volume mode:
# export AWS_ACCESS_KEY_ID="..."
# export AWS_SECRET_ACCESS_KEY="..."
{% endif %}
bash src/connectors/{{ source }}/scripts/load-secrets.sh
```
```

#### §Run the job (page §5)

```markdown
## Run the job

Before the connector ingests anything, the {{ source }} CLI must drop `--json` artefacts under the configured prefix(es) ({{ databricks_runtime.cli_artefact_prefixes | join(", ") }}).

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a one-shot orchestration:

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```
```

#### §Verify (page §6)

```markdown
## Verify

```sql
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }};

SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}' AND category = 'secrets';

-- Verify Raw / RawV2 redaction (must NOT appear in silver):
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.silver.findings
  WHERE tool_source = '{{ databricks_runtime.tool_source_label }}'
    AND raw_payload LIKE '%"RawV2"%';
-- Expected: 0 (raw fields dropped at Bronze→Silver)
```
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| 0 rows in `{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }}` | No artefacts have landed under the configured prefix. Verify with object-storage `ls`. |
| Auto Loader fails on permission error (S3 mode) | The `{{ source }}_aws_credentials` secret is missing or wrong. Re-export `AWS_ACCESS_KEY_ID`+`AWS_SECRET_ACCESS_KEY` and re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh`. |
| Redaction check returns rows | The Bronze→Silver transform is not dropping `Raw` / `RawV2`. This is a bug in `transform.py` — secrets findings MUST drop raw fields per `references/secrets.md`. |
```
