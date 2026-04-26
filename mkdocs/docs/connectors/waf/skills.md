# WAF skills

Four skills cover the connector lifecycle for WAF sources. Each carries a WAF-specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: WAF reference

Facts the analyze-source skill needs to write a complete Reference section for a WAF source. WAF sources project edge-event records into finding-shape rows on `silver.findings` per the trufflehog convention — severity is derived from `action`, status is the literal `open`, and `finding_id` is a deterministic SHA-256 hash so re-deliveries collapse at MERGE.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. WAF sources emit edge-event records that are projected into finding-shape rows on `silver.findings`.

- Apply: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (for example sampled-request SDK calls); for log-stream consumption (the preferred mode), these are N/A.
- `REQ-TRF-STS` applies in degraded form — WAF events have no native lifecycle, so the connector emits the literal `open` per the trufflehog convention; `status_canonical` never transitions. The catalog matrix marks this `N/A` (matching the trufflehog row).
- `REQ-DEDUP` stays N/A on the catalog matrix — WAF events still don't share dedup tuples with SAST/SCA/secrets/DAST. Replay deduplication is achieved via the deterministic `finding_id` hash plus the Bronze→Silver MERGE; no `dedup_links` rows are emitted.

### Default severity

`medium`. Severity is not a first-class field on a WAF event; the canonical severity is **derived** from the `action` field via an action-keyed lookup table (e.g. `block→high`, `count→medium`, `allow→low`) — analogous to the secrets convention but data-driven from action rather than fixed.

The Reference section's Enumerations fact MUST disclose the derivation rule (action → canonical severity) and list every documented action value.

### Incremental strategy

Timestamp-based high-water mark over the log stream. The connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run.

For AWS deployments the reference pattern is **Firehose to S3** or **CloudWatch Logs into Bronze** via an autoloader-style ingestion. For on-prem appliances the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example `GetSampledRequests`) are supported as a fallback only — the WAF specification requires the connector to PREFER log-stream consumption over sampled SDK calls because samples lose fidelity under high-volume rules.

### Deduplication key

`REQ-DEDUP` is N/A on the catalog matrix — WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so no `dedup_links` rows are emitted. Replay deduplication (recovering from re-delivered events) is achieved instead by the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE — re-delivered events collapse onto the same `finding_id` at MERGE time.

### Target Silver tables

`silver.findings` — the canonical findings table, same target as SAST/SCA/secrets/DAST. WAF events are projected into finding-shape rows: each event becomes one finding row with severity derived from action (via the action-keyed lookup), status set to the literal `open` (no native lifecycle), and a deterministic `finding_id` SHA-256 hashed from `(webacl_arn, request_id, timestamp_ms)`.

WAF events have no native `repository_id`, so `repository_id` is null on the emitted rows. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).

WAF-specific telemetry that is NOT carried on `silver.findings` — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped from the canonical record. Operators query upstream WAF logs (S3 / CloudWatch) for that telemetry. The headline schema deviation that previously distinguished WAF (a dedicated `silver.waf_events` table) has been collapsed.

### Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs (AWS WAF, Cloudflare, Azure Front Door WAF) authenticate via IAM role or access key bound to the cloud account hosting the WebACLs. On-prem appliances (F5 ASM, Imperva, ModSecurity) authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. For AWS WAF, autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern — this fits the Lakeflow Connect / SDK envelope. SDK-based sampled-request fallback is permitted only when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into Bronze for downstream extrapolation.

### Quirks

- **Finding-shape on `silver.findings`.** WAF now follows the trufflehog convention: each WAF event becomes one finding row on `silver.findings` (the same canonical table SAST/SCA/secrets/DAST target). The previous schema deviation (a dedicated `silver.waf_events` table) has been collapsed.
- **Severity is derived.** Severity comes from the `action` field via an action-keyed lookup (`block→high`, `count→medium`, `allow→low`, etc.). The lookup is action-keyed, not severity-keyed.
- **Status is the literal `open`.** WAF events have no native lifecycle; the connector follows the trufflehog convention and writes the literal `open` to `status_canonical`. `status_canonical` never transitions.
- **Deterministic `finding_id`.** Each row's `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)`. Re-deliveries collapse at MERGE time.
- **WAF-only telemetry is dropped.** `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself are NOT carried on `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that detail.
- **Sampling weight.** Where the source returns statistical samples (sampled SDK calls), each record carries a sampling weight that MUST be preserved into Bronze for downstream extrapolation (it is not projected onto `silver.findings`).
- **Application linkage is deferred.** WAF events have no native `repository_id`; `repository_id` is null on emitted rows. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The Reference section MUST list every action the source emits — this drives the severity-derivation lookup.
- **Log-stream over SDK.** Prefer log-stream consumption over sampled SDK calls; the Reference section's Quirks fact MUST disclose the chosen mode and justify any deviation.

*Rendered from `.claude/skills/analyze-source/references/waf.md`. Source-of-truth lives in the skill file.*

## provision-source: WAF reference

Facts the provision-source skill needs to emit the source-side runtime for a WAF source. WAF connectors follow a **bucket-policy-only** runtime shape (canonical follower: AWS WAF). The operator provisions the WebACL, the Kinesis Firehose delivery stream, and the destination S3 bucket out of band; the runtime wires those external resources into the connector by attaching the Firehose-write bucket policy and surfacing the bronze schema name and bucket ARN as outputs.

### Runtime shape

`runtime_provisioner: terraform-aws-bucket-policy`. Provider stack: `hashicorp/aws` + `databricks/databricks` (the latter for `versions.tf` parity, currently unused — kept for forward-compatibility if a future revision adds UC Volume / external location bindings).

Resources / data sources:

- `data "aws_s3_bucket" "waf_logs"` — references the operator-supplied bucket (does NOT create it). Bucket name is parsed out of the ARN via `element(split(":::", var.aws_waf_log_bucket_arn), 1)`.
- `aws_s3_bucket_policy.waf_logs_firehose` — bucket policy granting the Firehose service principal (`firehose.amazonaws.com`) `s3:PutObject` + `s3:PutObjectAcl` on `${var.aws_waf_log_bucket_arn}/*`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`. Sid `AllowFirehoseWrite`.

It does **not** create the WebACL, the Firehose delivery stream, or the S3 bucket. Those are operator prerequisites.

### `operational.yml.source_runtime` fields

Required: `runtime_provisioner` (always `terraform-aws-bucket-policy` for WAF), `catalog_var_name`, `bronze_schema_name` (default `bronze_aws_waf`), `aws_region_var_name`, `aws_account_id_var_name`, `log_bucket_arn_var_name`. Optional with category defaults: `aws_region_default` (`us-east-1`), `firehose_service_principal` (`firehose.amazonaws.com`), `firehose_actions` (`["s3:PutObject", "s3:PutObjectAcl"]`), `bucket_policy_sid` (`AllowFirehoseWrite`), `secret_keys_external` (`["waf_log_bucket", "aws_waf_iam_role_arn"]` — loaded by `scripts/load-secrets.sh`, NOT by Terraform), `sample_artefact_path` (`runtime/files/sample.json`), `terraform_required_version` (`>= 1.5`).

### Variables exposed

Required: `catalog`, `aws_waf_account_id`, `aws_waf_log_bucket_arn`. Optional: `aws_region` (default `us-east-1`).

### Outputs

`bronze_schema_full_name` (= `${var.catalog}.bronze_aws_waf`), `s3_bucket_arn` (echo of the operator-supplied bucket ARN).

### Operator-authored sidecar

One `runtime/files/*` reference: `runtime/files/sample.json` — a sanitised representative WAFv2 log record. Each S3 object delivered by Firehose contains one or more records in this form, separated by newlines (typically gzipped). The bronze envelope (`sql/event_envelope.sql`) lands the raw payload as a string and extracts the WebACL ID at ingest time for joinability. Operator-authored — the skill emits the README reference but never the file body.

### `runtime/install.sh` shape

`terraform init` + `terraform apply -auto-approve` wrapper, with TF_VAR exports for `CATALOG`, `AWS_WAF_ACCOUNT_ID`, `AWS_WAF_LOG_BUCKET_ARN` (e.g. `arn:aws:s3:::my-org-waf-logs`). Optional override: `AWS_REGION`.

Prerequisites: WAFv2 enabled in `$AWS_WAF_ACCOUNT_ID`, fronting CloudFront, ALB, or API Gateway; WebACL configured with logging enabled, sending logs via Kinesis Firehose to the target S3 bucket; the target bucket exists and is owned by the operator (in the same account as the Firehose); AWS credentials usable from Terraform with permissions to attach an S3 bucket policy on the target bucket; for runtime ingestion, AWS credentials with `s3:GetObject` on the log bucket loaded into the Databricks `mvp-connectors` scope via `bash scripts/load-secrets.sh`.

### Page §Source provisioning section template

Inserted after `## User inputs` and before `## Secrets`. Section heading: `## Optional source runtime`. Body explains that the module wires the operator-owned S3 bucket that Kinesis Firehose delivers WAFv2 log records to into the connector — the runtime **does not** create the WebACL, Firehose, or bucket; what it *does* create is the S3 bucket policy granting the Firehose service principal write access, scoped via `aws:SourceAccount`. Documents the apply command (one-liner against `catalog`, `aws_waf_account_id`, `aws_waf_log_bucket_arn`), with a cross-link to `runtime/files/sample.json` for the log-record format reference.

> **Secrets-out-of-Terraform note (carried into the page):** secret values for the WAF connector (`waf_log_bucket`, `aws_waf_iam_role_arn`) live in the Databricks `mvp-connectors` scope and are loaded by `scripts/load-secrets.sh`. They do NOT flow through this Terraform module — `main.tf` only manages the S3 bucket policy. Keeping secret values out of Terraform state is intentional.

### Teardown caveat

`terraform destroy` removes the bucket policy only. The underlying bucket and any log objects already delivered to it are **not** managed by this module. Delete them out of band if no longer needed. The WebACL and Firehose delivery stream are also not managed by this module.

*Rendered from `.claude/skills/provision-source/references/waf.md`. Source of truth lives in the skill file.*

## generate-connector: WAF reference

Facts the generate-connector skill needs to emit a WAF connector module. WAF sources project edge-event records into finding-shape rows on `silver.findings` per the trufflehog convention — severity is derived from `action`, status is the literal `open`, and `finding_id` is a deterministic SHA-256 hash so re-deliveries collapse at MERGE.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests`); for log-stream consumption (the preferred mode), they are N/A.
- `REQ-TRF-STS` applies in degraded form — bind a test asserting that `status_canonical` is the literal `open` (per the trufflehog convention) and never transitions, since WAF events have no native lifecycle. The catalog matrix marks this `N/A` (matching the trufflehog row's pattern for literal-status sources).
- `REQ-DEDUP` stays N/A — WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so the connector emits no `dedup_links` rows. Replay deduplication is achieved via the deterministic `finding_id` hash plus the Bronze→Silver MERGE; bind a single test asserting that re-delivered events collapse onto the same `finding_id`.

### Default severity

`medium`. Severity is **derived**, not source-supplied — there is no `severity` field on a WAF event. The canonical severity is computed from the `action` field (block / allow / count / challenge / captcha) via an action-keyed lookup.

The `config/severity/{source}.yml` lookup is therefore action-keyed, not severity-keyed. Generate the lookup with action-to-severity mappings covering every documented action value (e.g. `block: high`, `count: medium`, `allow: low`, `challenge: low`, `captcha: low`). The `mapping.yml` severity field references the lookup with `action` as the source path:

```yaml
severity:
  source_path: action
  lookup: config/severity/{source}.yml
```

The configurable default for unmatched actions is `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream. Encode in `config.yml`:

- The connector records the last event-time ingested per WebACL or rule group and advances forward on each run.
- For AWS deployments: autoloader-style ingestion from a Firehose-to-S3 prefix or CloudWatch Logs export.
- For on-prem appliances: the same pattern over the forwarded syslog bucket.
- Sampled SDK calls (`GetSampledRequests`) are a **fallback only**. Prefer log-stream consumption — samples lose fidelity under high-volume rules. Where the fallback is used, preserve the statistical sampling weight (`Weight` field) into Bronze for downstream extrapolation (not onto `silver.findings`).

### Deduplication key

Per canonical mapping: `REQ-DEDUP` is N/A for WAF — WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so the canonical `dedup_links` table does not get WAF rows. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in a transform-level comment to document the absence.

Replay deduplication (within-source, recovering from re-delivered events) is achieved by the deterministic `finding_id`: a SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` projected onto each row. Re-delivered events produce the same `finding_id` and collapse at the Bronze→Silver MERGE:

```python
import hashlib

def derive_finding_id(webacl_arn: str, request_id: str, timestamp_ms: int) -> str:
    """Deterministic SHA-256 finding_id; re-delivered WAF events collapse at MERGE."""
    payload = f"{webacl_arn}|{request_id}|{timestamp_ms}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

Do NOT emit `dedup_links` rows — the canonical `dedup_links` table targets cross-tool finding overlap, which WAF does not participate in.

### Target Silver tables

`silver.findings` — the canonical findings table. WAF follows the trufflehog convention: each WAF event becomes one finding row on `silver.findings`, severity is derived from `action` via the action-keyed lookup, status is the literal `open` (no native lifecycle), and `finding_id` is the deterministic SHA-256 hash described above. The `mapping.yml` block targets `silver.findings` with the canonical envelope columns populated; `cwe_id`, `cve_id`, `repository_id`, `file_path`, and `start_line` are null. The previous schema deviation (a dedicated `silver.waf_events` table) has been collapsed; WAF now matches every other category's `silver.findings` target.

WAF events have no native `repository_id`; the connector emits null `repository_id` on every row. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP). Do NOT emit a transform-time join against `silver.deployments`; do NOT encode an ARN-to-application resolution in `transform.py`.

WAF-specific telemetry that is NOT carried on `silver.findings` — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped from the canonical record. Operators query upstream WAF logs (S3 / CloudWatch) for that detail; do not project these fields into `silver.findings`.

### Authentication norms

Account-scoped, NOT per-tenant:

- **Cloud-native WAFs** (AWS WAF, Cloudflare, Azure Front Door WAF): IAM role or access key bound to the cloud account hosting the WebACLs.
- **On-prem appliances** (F5 ASM, Imperva, ModSecurity): service credential bound to the log-aggregation tier.

`ingest.py` reads credentials via the helper in `src/common/`; `config.yml` references the secret-scope key names. There is no per-application authentication axis; do not generate one.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **AWS WAF**: autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern. This fits the Lakeflow Connect / SDK envelope.
- **SDK-based sampled-request fallback**: permitted only when full-log ingestion is not yet provisioned. Preserve the sampling weight into Bronze.
- The artefact-collection / autoloader pattern is the dominant WAF mode and aligns with Lakeflow Connect; no CLI-artefact deviation is needed.

### Quirks

- **Finding-shape on `silver.findings`.** Each WAF event projects to one finding row on the canonical findings table — same target as SAST/SCA/secrets/DAST. Emit a finding-only block in `mapping.yml`; reuse the canonical envelope columns. The previous `silver.waf_events` schema deviation has been collapsed.
- **Severity is derived.** The `action` field drives canonical severity through the action-keyed lookup. Generate the lookup as action-keyed; do NOT generate a severity-keyed lookup that mirrors a source severity field (there is none).
- **Status is the literal `open`.** Per the trufflehog convention, write `open` to `status_canonical`; the field never transitions. The `config/status/{source}.yml` lookup contains a comment to that effect.
- **Deterministic `finding_id`.** Project a SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` as the `finding_id`. Re-delivered events collapse at the Bronze→Silver MERGE.
- **WAF-only telemetry is dropped.** Do NOT project `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, or the `action` value itself onto `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that telemetry.
- **Sampling weight preserved in Bronze only.** Where the source returns statistical samples, project the `Weight` field into Bronze (not onto `silver.findings`). Downstream extrapolation depends on it.
- **Application linkage is deferred.** WAF events have no native `repository_id`; emit `repository_id = null`. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP). Do NOT emit a `silver.deployments` join in `transform.py`.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The severity lookup MUST cover every action the source emits — exhaustive over the documented vocabulary.
- **Log-stream over SDK.** Prefer log-stream consumption. SDK sampled-request mode is fallback-only; document the deviation in a top-of-file comment in `ingest.py` if used.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for WAF connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The WAF `databricks_runtime` schema (reverse-engineered from the AWS WAF follower) covers seventeen fields: `secret_scope`, `bronze_schema`, `bronze_tables`, `envelope_table` (default `event_envelope`), `cron_schedule` (default `0 */15 * * * ?` — every 15 min), `uc_catalog_var`, `job_name` (kebab-case, e.g. `aws-waf-connector`), `default_target`, `default_catalog`, `secret_env_vars` (e.g. `WAF_LOG_BUCKET → waf_log_bucket`, `AWS_WAF_IAM_ROLE_ARN → aws_waf_iam_role_arn`), `extra_install_env_vars` (typically required: `AWS_WAF_ACCOUNT_ID`, `AWS_WAF_LOG_BUCKET_ARN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), `tool_source_label` (discriminates WAF rows from other tools' findings on the canonical `silver.findings` table; the verify-step queries `WHERE tool_source = '{tool_source_label}'`), `entry_wrappers` (`false` — ingest runs in-notebook from `ingest.py`), `ingestion_mode` (`log_stream` or `sdk_sampled`; default `log_stream`), `log_stream_prefix` (default `waf/firehose/`), `firehose_account_id_env` (default `AWS_WAF_ACCOUNT_ID`), `webacl_log_bucket_arn_env` (default `AWS_WAF_LOG_BUCKET_ARN`).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. Iterates over the env-var/secret-key pairs and runs `databricks secrets put-secret` per pair.
- **`scripts/install.sh`** — streamlined three-step shape (load-secrets → `databricks bundle run {job_name}` → echo verify). The runbook-grade verify-counts-via-SQL-warehouse flow lives in the docs page, not the install script.
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`. **WAF source-side runtime is mandatory for the log-stream path** — `runtime/install.sh` attaches the Firehose-write S3 bucket policy without which the autoloader has nothing to read.
- **`sql/<envelope>.sql`** — REQUIRED. **`CREATE TABLE`** shape (companion to the autoloader-managed bronze table). Autoloader reads gzipped JSON files from the S3 bucket and lands them with columns `raw_payload`, `webacl_id` (extracted at ingest from `terminatingRuleArn` or `webaclId` for joinability), `ingested_at`, `run_id`. The transform projects this into `silver.findings`.
- **No `*_entry.py` wrappers** — `entry_wrappers=false`. The `resources/job.yml` `notebook_path` points at `../ingest.py` directly.
- **`resources/` extras** — alongside `resources/{source}-job.yml` (15-min cron, with an extra `ingestion_mode` job parameter `log_stream | sdk_sampled`), WAF emits `resources/schemas.yml` (bronze only). `resources/connection.yml` is N/A — the workspace AWS service credential reads S3 directly; no UC connection. `resources/pipeline.yml` is N/A — notebook job, not Lakeflow Connect. `resources/volumes.yml` is N/A — the workspace AWS service credential reads from the S3 prefix directly; AWS WAF does not emit a UC Volume.
- **Connector page §4–§7 templates** — §Secrets (table mapping `secret_key` ↔ `env_var` with the workspace-AWS-service-credential note), §Run the job (notebook job named `{job_name}` with the Firehose-buffer-flush callout — Firehose buffers up to 5 minutes or 5 MiB, so smoke tests should generate blockable requests then wait ~5 minutes before the autoloader picks them up on the next 15-min tick), §Verify (Bronze count plus top-terminating-rules and severity-distribution aggregations against `silver.findings` filtered by `tool_source = '{tool_source_label}'`), and §Troubleshooting (no-records-after-buffer-flush, severity-canonical mis-derived from `action`, autoloader-prefix mismatch).

*Rendered from `.claude/skills/generate-connector/references/waf.md`. Source-of-truth lives in the skill file.*

## validate-implementation: WAF reference

Facts the validate-implementation skill needs to populate the Validation table for a WAF connector. WAF sources project edge-event records into finding-shape rows on `silver.findings` per the trufflehog convention — severity is derived from `action` via the action-keyed lookup, status is the literal `open`, and `finding_id` is a deterministic SHA-256 hash so re-deliveries collapse at MERGE.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The AWS WAF column of the traceability matrix is the MVP-built profile.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-STS` — degraded form: asserts `status_canonical` is the literal `open` on every emitted row and never transitions, per the trufflehog convention. The catalog matrix marks this `N/A` (matching the trufflehog row's pattern for literal-status sources).
- `REQ-TRF-TS`
- `REQ-DQ` — also covers the deterministic-`finding_id` replay-deduplication assertion (re-delivered events collapse onto the same `finding_id` at MERGE).

Mark `N/A`:

- `REQ-ING-PAG`, N/A: log-stream consumption (the preferred mode) has no API pagination. Apply only when the connector consumes a paginated SDK surface (e.g. `GetSampledRequests` fallback); otherwise mark `N/A` with the rationale "log-stream mode has no API pagination".
- `REQ-ING-RL`, N/A: same rationale; log-stream consumption has no API rate limit. Apply only when the SDK fallback is in use.
- `REQ-DEDUP`, N/A on the catalog matrix: WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so the connector emits no `dedup_links` rows. Replay deduplication is achieved instead by the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE — re-delivered events collapse onto the same `finding_id` at MERGE time. That replay assertion is bound under `REQ-DQ`, not `REQ-DEDUP`.

### Default severity

`medium` configurable default; severity is **derived** from the `action` field via an action-keyed lookup, not source-supplied. The `REQ-TRF-SEV` test asserts the action-keyed lookup covers every documented action (`block`, `allow`, `count`, `challenge`, `captcha`) and that undocumented actions fall through to `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream. The connector records the last event-time ingested per WebACL or rule group and advances forward each run. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the timestamp advancement; SDK-fallback mode preserves `Weight` into Bronze and is also asserted under `REQ-ING-HWM` plus `REQ-TRF-MAP`.

### Deduplication key

Per `mkdocs/docs/platform/reference/canonical-mapping.md`: `REQ-DEDUP` is N/A for WAF — WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so no `dedup_links` rows are emitted. Replay deduplication is instead achieved via the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE; re-delivered events collapse onto the same `finding_id`. The test suite asserts this collapse under `REQ-DQ`, NOT under `REQ-DEDUP`. The test suite does NOT emit `dedup_links` rows for WAF.

### Target Silver tables

`silver.findings` — the canonical findings table, same target as SAST/SCA/secrets/DAST. The `REQ-TRF-MAP` test asserts the connector targets `silver.findings` with the canonical envelope columns populated; `cwe_id`, `cve_id`, `repository_id`, `file_path`, and `start_line` are null on every emitted row. The headline schema deviation that previously distinguished WAF (a dedicated `silver.waf_events` table) has been collapsed; WAF now matches every other category's `silver.findings` target.

The `REQ-TRF-MAP` test additionally asserts:

- `severity_canonical` is derived from `action` via the action-keyed lookup at `config/severity/{source}.yml`.
- `status_canonical` is the literal `open` on every row (asserted under `REQ-TRF-STS` in degraded form).
- `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` so re-deliveries collapse at MERGE.
- `repository_id` is null on every row (WAF events have no native repository linkage).
- WAF-specific telemetry (`source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, the `action` value itself) is NOT projected onto `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that detail.
- No transform-time join against `silver.deployments` is emitted — application linkage is deferred to Gold-side aggregations, which bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).

### Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs use IAM role or access key; on-prem appliances use a service credential bound to the log-aggregation tier. The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. Autoloader-style ingestion from the Firehose-to-S3 prefix (AWS WAF) fits the Lakeflow Connect / SDK envelope; no CLI-artefact deviation is needed. The validation suite verifies pagination and rate-limit absence under the N/A markings rather than asserting a tool-choice fact directly.

### Quirks

- **Finding-shape on `silver.findings`.** `REQ-TRF-MAP` asserts the connector targets `silver.findings` with the canonical envelope columns populated; `cwe_id`/`cve_id`/`repository_id`/`file_path`/`start_line` are null. The previous `silver.waf_events` schema deviation has been collapsed. The test fails if a dedicated `silver.waf_events` table is targeted.
- **Severity is derived.** `REQ-TRF-SEV` asserts the lookup is action-keyed, not severity-keyed. A severity-keyed lookup that mirrors a source severity field is a `FAIL`.
- **Status is the literal `open`.** `REQ-TRF-STS` (degraded form) asserts `status_canonical` is the literal `open` on every emitted row and never transitions, per the trufflehog convention. The `config/status/{source}.yml` lookup contains a comment to that effect.
- **Deterministic `finding_id`.** `REQ-DQ` asserts `finding_id` is a SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` and that re-delivered events collapse onto the same `finding_id` at the Bronze→Silver MERGE.
- **WAF-only telemetry is dropped.** `REQ-TRF-MAP` asserts `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself are NOT projected onto `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that telemetry.
- **Sampling weight preserved in Bronze only.** Where the SDK sampled-request fallback is in use, `REQ-TRF-MAP` asserts the `Weight` field is projected into Bronze (not onto `silver.findings`). Downstream extrapolation depends on it.
- **Application linkage is deferred.** `REQ-TRF-MAP` asserts `repository_id` is null on every row and that no transform-time join against `silver.deployments` is emitted. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. `REQ-TRF-SEV` asserts coverage over the full action vocabulary the source emits.
- **Log-stream over SDK.** `REQ-ING-PAG` and `REQ-ING-RL` are bound only when the SDK fallback is in use. Log-stream-only deployments mark them `N/A` with the rationale "log-stream mode has no API pagination/rate limit".

*Rendered from `.claude/skills/validate-implementation/references/waf.md`. Source-of-truth lives in the skill file.*
