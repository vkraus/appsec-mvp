# generate-connector — WAF reference

Facts the generate-connector skill needs to emit a WAF connector module. WAF sources emit append-only edge-event records — event-shaped, not finding-shaped.

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

- Bind: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests`); for log-stream consumption (the preferred mode), they are N/A.
- Do NOT bind `REQ-TRF-STS` — WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form — the dedup is event-stream replay-window deduplication, not cross-tool finding overlap. Bind a single test asserting the replay-window behaviour.

## Default severity

`medium`. Severity is **derived**, not source-supplied — there is no `severity` field on a WAF event. The canonical severity is computed from `action` (block / allow / count / challenge / captcha) plus rule-group category.

The `config/severity/{source}.yml` lookup is therefore action-keyed, not severity-keyed. Generate the lookup with action-to-severity mappings covering every documented action value (e.g. `block: high`, `count: low`, `allow: low`, `challenge: medium`). The `mapping.yml` severity field references the lookup with `action` as the source path:

```yaml
severity:
  source_path: action
  lookup: config/severity/{source}.yml
```

The configurable default for unmatched actions is `medium` with a data-quality warning.

## Incremental strategy

Timestamp-based HWM over the log stream. Encode in `config.yml`:

- The connector records the last event-time ingested per WebACL or rule group and advances forward on each run.
- For AWS deployments: autoloader-style ingestion from a Firehose-to-S3 prefix or CloudWatch Logs export.
- For on-prem appliances: the same pattern over the forwarded syslog bucket.
- Sampled SDK calls (`GetSampledRequests`) are a **fallback only**. Prefer log-stream consumption — samples lose fidelity under high-volume rules. Where the fallback is used, preserve the statistical sampling weight (`Weight` field) into Bronze for downstream extrapolation.

## Deduplication key

Per canonical mapping: not currently specified for WAF — append-only event log; cross-tool overlap not yet defined. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a dedup-key tuple for WAF in the current MVP scope.

For replay-window deduplication (within-source, recovering from re-delivered events), the WAF capability surface uses `(timestamp, rule_id, source_ip, request_id)` per the `analyze-source` WAF reference. Encode this tuple in `transform.py` for replay deduplication only:

```python
replay_dedup_key = (row["timestamp"], row["rule_id"], row["source_ip"], row["request_id"])
```

Do NOT emit `dedup_links` rows — the canonical `dedup_links` table targets cross-tool finding overlap, which WAF does not participate in. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in a transform-level comment to document the absence.

## Target Silver tables

`silver.waf_events` (plural) per `mkdocs/docs/platform/reference/silver-table-ownership.md` patterns and the WAF capability surface at `mkdocs/docs/connectors/waf/index.md`. The `mapping.yml` block targets `silver.waf_events`, NOT `silver.findings` — this is the headline schema deviation for WAF.

`transform.py` MUST emit a join against `silver.deployments` to resolve the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage) into `application_id`. The ARN field is encoded in `mapping.yml` and the connector page Resource schema excerpt documents the field name.

## Authentication norms

Account-scoped, NOT per-tenant:

- **Cloud-native WAFs** (AWS WAF, Cloudflare, Azure Front Door WAF): IAM role or access key bound to the cloud account hosting the WebACLs.
- **On-prem appliances** (F5 ASM, Imperva, ModSecurity): service credential bound to the log-aggregation tier.

`ingest.py` reads credentials via the helper in `src/common/`; `config.yml` references the secret-scope key names. There is no per-application authentication axis; do not generate one.

## Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **AWS WAF**: autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern. This fits the Lakeflow Connect / SDK envelope.
- **SDK-based sampled-request fallback**: permitted only when full-log ingestion is not yet provisioned. Preserve the sampling weight into Bronze.
- The artefact-collection / autoloader pattern is the dominant WAF mode and aligns with Lakeflow Connect; no CLI-artefact deviation is needed.

## Quirks

- **Event-shaped, not finding-shaped.** Each record is a single edge observation, not a triaged vulnerability. The Silver target is `silver.waf_events`, NOT `silver.findings`. Emit the matching schema in `mapping.yml`; do not reuse the finding shape.
- **Severity is derived.** Action plus rule-group category drives canonical severity through the action-keyed lookup. Generate the lookup as action-keyed; do NOT generate a severity-keyed lookup that mirrors a source severity field (there is none).
- **Sampling weight preserved.** Where the source returns statistical samples, project the `Weight` field into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** WebACL ARN → `silver.deployments` join at transform time. Encode the ARN field name in `mapping.yml`; emit the join in `transform.py` (mirrors the DAST `target` join in shape).
- **Append-only stream.** No status lifecycle; do not project a `status` field; do not generate status-transition code. The `config/status/{source}.yml` lookup MUST exist (per the every-connector-has-both-files contract) and contain `# N/A — WAF events are append-only; no status lifecycle`.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The severity lookup MUST cover every action the source emits — exhaustive over the documented vocabulary.
- **Log-stream over SDK.** Prefer log-stream consumption. SDK sampled-request mode is fallback-only; document the deviation in a top-of-file comment in `ingest.py` if used.

## operational.yml.databricks_runtime schema

Reverse-engineered from `src/connectors/aws_waf/...` (live follower).

| Field | Type | Required | Default | Source-of-derivation |
|---|---|---|---|---|
| `secret_scope` | string | yes | `mvp-connectors` | `scripts/load-secrets.sh` `SCOPE="mvp-connectors"`; `config.yml` `bucket_secret_scope: mvp-connectors`. |
| `bronze_schema` | string | yes | `bronze_{source}` | `resources/schemas.yml` `name: bronze_aws_waf`; `sql/event_envelope.sql` `${catalog}.bronze_aws_waf.event_envelope`. |
| `bronze_tables` | list[string] | yes | (none) | `config.yml` `bronze_table: ${catalog}.bronze_aws_waf.events`; `sql/event_envelope.sql` `bronze_aws_waf.event_envelope`. |
| `envelope_table` | string | yes | `event_envelope` | `sql/event_envelope.sql` `CREATE TABLE … bronze_aws_waf.event_envelope`. |
| `cron_schedule` | string | yes | `0 */15 * * * ?` (every 15 min) | `resources/job.yml` `quartz_cron_expression`. |
| `uc_catalog_var` | string | yes | `${var.catalog}` | `resources/schemas.yml` `catalog_name`; `sql/event_envelope.sql` `${catalog}` references. |
| `job_name` | string | yes | `{source}-connector` (kebab) | `resources/job.yml` `jobs.{job_name}`. aws_waf=`aws-waf-connector`. |
| `default_target` | string | no | `dev` | `scripts/install.sh` `databricks bundle run aws-waf-connector --target dev`. |
| `default_catalog` | string | no | `appsec_dev` | Implicit; verify-step in mkdocs page uses `appsec_dev.bronze_aws_waf.event_envelope`. |
| `secret_env_vars` | list[{env_var,secret_key}] | yes | (none) | `scripts/load-secrets.sh` put-secret lines. aws_waf: `(WAF_LOG_BUCKET→waf_log_bucket, AWS_WAF_IAM_ROLE_ARN→aws_waf_iam_role_arn)`. |
| `extra_install_env_vars` | list[string] | yes (typically) | (none) | `scripts/install.sh` extra `: "${VAR:?...}"`. aws_waf adds `(AWS_WAF_ACCOUNT_ID, AWS_WAF_LOG_BUCKET_ARN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)`. |
| `tool_source_label` | string | yes | `{source}` | Verify-step assumption — silver.waf_events does not have a `tool_source` discriminator (single-source table currently); kept for symmetry. |
| `entry_wrappers` | bool | yes | `false` | aws_waf `resources/job.yml` `notebook_path: ../ingest.py` (no entry wrappers). |
| `ingestion_mode` | enum(`log_stream`, `sdk_sampled`) | yes | `log_stream` | `config.yml` `ingestion_mode:`; `resources/job.yml` parameter `ingestion_mode default: "log_stream"`. |
| `log_stream_prefix` | string | yes (log_stream) | `waf/firehose/` | `config.yml` `log_stream.prefix: waf/firehose/`. |
| `firehose_account_id_env` | string | yes (Firehose path) | `AWS_WAF_ACCOUNT_ID` | `scripts/install.sh` env var checks; runtime/main.tf interpolation. |
| `webacl_log_bucket_arn_env` | string | yes (Firehose path) | `AWS_WAF_LOG_BUCKET_ARN` | `scripts/install.sh` env var checks. |

17 fields.

**Judgment call:** WAF is event-shaped, not finding-shaped. The verify-step queries `silver.waf_events` (NOT `silver.findings`) — this differs from every other category. `tool_source_label` is retained in the schema for cross-category symmetry, but is unused in the verify-step SQL.

## Databricks-side production-shape

### scripts/load-secrets.sh template

Same shape. aws_waf example writes `waf_log_bucket` from `WAF_LOG_BUCKET` and `aws_waf_iam_role_arn` from `AWS_WAF_IAM_ROLE_ARN`.

```bash
#!/usr/bin/env bash
# Populate {{ source }} connector secrets into the {{ databricks_runtime.secret_scope }} scope.
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

Minimal three-step shape (load-secrets → bundle run → echo verify). aws_waf shape has a streamlined install.sh (3-line core) — the runbook-grade "verify counts via SQL warehouse" flow lives in the docs page, not the install script.

```bash
#!/usr/bin/env bash
set -euo pipefail
{% for v in databricks_runtime.extra_install_env_vars %}
: "${{ '{' }}{{ v }}:?required{{ '}' }}"
{% endfor %}

echo "Step 1/3: Loading secrets..."
bash src/connectors/{{ source }}/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run {{ databricks_runtime.job_name }} --target {{ databricks_runtime.default_target }}
echo "Step 3/3: Run verification SQL — see runbook"
echo "✓ {{ source | upper }} connector install complete."
```

### install.sh (top-level) template

Same chain as other categories. WAF source-side runtime is `hashicorp/aws` (Firehose, IAM, S3 bucket policy) — the runtime is mandatory for the log-stream path.

### *_entry.py applicability

**N/A for WAF.** aws_waf shape has no entry wrappers; ingest runs in-notebook from `ingest.py`.

### sql/<envelope>.sql template

REQUIRED. CREATE TABLE shape (companion to the autoloader-managed bronze table).

```sql
-- Bronze envelope for {{ source }} log records.
-- Autoloader reads gzipped JSON files from the S3 bucket and lands them
-- here for the WAF transform to project into silver.waf_events.

CREATE TABLE IF NOT EXISTS {{ databricks_runtime.uc_catalog_var }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }} (
  raw_payload STRING,
  webacl_id STRING,        -- terminatingRuleArn or webaclId, extracted at ingest for joinability
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT 'Raw {{ source }} log records; transformed into silver.waf_events.';
```

### resources/extras (per category)

- `resources/job.yml` (8-file core) with `notebook_path: ../ingest.py` / `../transform.py`. 15-min cron. Has an extra `ingestion_mode` job parameter (log_stream | sdk_sampled).
- `resources/schemas.yml` — `bronze_{source}` only:

  ```yaml
  resources:
    schemas:
      {{ databricks_runtime.bronze_schema }}:
        catalog_name: {{ databricks_runtime.uc_catalog_var }}
        name: {{ databricks_runtime.bronze_schema }}
  ```

- `resources/connection.yml` — **N/A** (workspace AWS service credential reads S3 directly; no UC connection).
- `resources/pipeline.yml` — **N/A** (notebook job, not Lakeflow Connect).
- `resources/volumes.yml` — **N/A** (workspace AWS service credential reads from the S3 prefix directly; aws_waf does not emit a UC Volume).

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

The Databricks workspace's AWS service credential (configured at platform setup) is what the autoloader uses to read S3.

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

The {{ source }} ingestion is a notebook job named `{{ databricks_runtime.job_name }}` (declared in `src/connectors/{{ source }}/resources/job.yml`) that runs every 15 minutes once enabled. Trigger an on-demand run:

```bash
databricks bundle run {{ databricks_runtime.job_name }} --target dev
```

For a smoke test, generate a few blockable requests against the WebACL-fronted endpoint, then wait ~5 minutes for Firehose to flush the buffered batch to S3 (Firehose buffers up to 5 minutes or 5 MiB) before the autoloader picks the records up on the next 15-minute pipeline tick.

Alternatively:

```bash
bash src/connectors/{{ source }}/scripts/install.sh
```
```

#### §Verify (page §6)

```markdown
## Verify

```sql
-- Bronze: raw WAF log envelopes landed by the autoloader.
SELECT count(*) FROM {{ databricks_runtime.default_catalog }}.{{ databricks_runtime.bronze_schema }}.{{ databricks_runtime.envelope_table }};

-- Top terminating rules (sanity-check the rule inventory).
SELECT rule_id, count(*)
  FROM {{ databricks_runtime.default_catalog }}.silver.waf_events
  GROUP BY rule_id
  ORDER BY 2 DESC
  LIMIT 10;

-- Severity distribution for a specific WebACL.
SELECT severity_canonical, count(*)
  FROM {{ databricks_runtime.default_catalog }}.silver.waf_events
  WHERE webacl_arn = '<your-webacl-arn>'
  GROUP BY severity_canonical;
```

Expected: bronze count > 0 after the Firehose buffer flushes; silver rows in `silver.waf_events` (NOT `silver.findings`); `severity_canonical` derived from `action`.
```

#### §Troubleshooting (page §7)

```markdown
## Troubleshooting

| Symptom | Fix |
|---|---|
| Bronze table empty after a successful job run | The Firehose buffer has not flushed yet (up to 5 minutes), or log delivery is not configured. Verify the bucket has objects with `aws s3 ls s3://your-bucket/AWSLogs/ --recursive`. |
| `AccessDenied` on S3 read in the job log | The IAM principal is missing `s3:GetObject` (or `s3:ListBucket`) on the log bucket. Update the IAM policy, then re-run `bash src/connectors/{{ source }}/scripts/load-secrets.sh` and re-deploy the bundle. |
| All `severity_canonical` values land on `medium` | The action-keyed lookup at `src/connectors/{{ source }}/severity.yml` fell through to the default. Inspect `raw_payload:action` in bronze and add the missing key to `severity.yml`. |
| Firehose objects present but no rows in bronze | Autoloader has not picked up the prefix yet. Confirm the connector's `log_stream.prefix` in `src/connectors/{{ source }}/config.yml` (default `{{ databricks_runtime.log_stream_prefix }}`) matches the actual S3 layout, and trigger another run. |
```
