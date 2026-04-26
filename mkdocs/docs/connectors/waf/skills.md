# WAF skills

Four skills cover the connector lifecycle for WAF sources. Each carries a WAF-specific reference. The procedural body of each skill is at [Connector skills](../../platform/reference/connector-skills.md).

## analyze-source: WAF reference

Facts the analyze-source skill needs to write a complete Reference section for a WAF source.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. WAF sources emit edge-event records treated as findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK API (for example sampled-request SDK calls). For log-stream consumption (the preferred mode), these are N/A.
- `REQ-TRF-STS` does not apply. WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form. Deduplication is event-stream deduplication (replay-window) rather than cross-tool finding overlap.

The AWS WAF traceability row currently shows N/A across the matrix because the source is documented but not built in the MVP. The MVP-built profile would be the set above.

### Default severity

`medium`. Severity is not a first-class field on a WAF event. The standard severity is **derived** from the action and rule-group category per a per-source lookup table, analogous to the secrets convention but data-driven from action+rule rather than fixed.

The Enumerations fact in the Reference section MUST disclose the derivation rule (action + rule-group category → standard severity) and list every documented action value.

### Incremental strategy

Timestamp-based high-water mark over the log stream. Per the WAF capability scope: the connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run.

For AWS deployments the reference pattern is **Firehose to S3** or **CloudWatch Logs into Bronze** via an autoloader-style ingestion. For on-prem appliances the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example `GetSampledRequests`) are supported as a fallback only. The WAF specification requires the connector to PREFER log-stream consumption over sampled SDK calls because samples lose fidelity under high-volume rules.

### Deduplication key

`(timestamp, rule_id, source_ip, request_id)` per the WAF capability scope, with the Silver event scope `(application_id, rule_id, timestamp)` per `mkdocs/docs/platform/reference/canonical-mapping.md`. Because WAF records are append-only event records rather than finding records, dedup is replay-window deduplication on the unique tuple, not cross-tool overlap linking.

### Target Silver tables

`silver.waf_events` per the WAF capability scope. Application scoping is derived at transform time from the resource ARNs associated with the WebACL (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments`. The Reference section MUST disclose this transform-time join.

### Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs (AWS WAF, Cloudflare, Azure Front Door WAF) authenticate via IAM role or access key bound to the cloud account hosting the WebACLs. On-prem appliances (F5 ASM, Imperva, ModSecurity) authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

### Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. For AWS WAF, autoloader-style ingestion from the Firehose-to-S3 prefix is the standard pattern. This fits the Lakeflow Connect / SDK envelope. SDK-based sampled-request fallback is permitted only when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into Bronze for downstream extrapolation.

### Quirks

- **Event records, not finding records.** Each record describes a single request observed at the edge, not a triaged vulnerability. The Silver target is `silver.waf_events`, not `silver.findings`. The Quirks fact in the Reference section MUST disclose this so generate-connector emits the right schema.
- **Severity is derived.** Severity comes from action + rule-group category, not from a source field. The lookup table is action-keyed, not severity-keyed.
- **Sampling weight.** Where the source returns statistical samples (sampled SDK calls), each record carries a sampling weight that MUST be preserved into Bronze for downstream extrapolation.
- **Application linkage via ARN.** Application scoping uses the resource ARNs associated with the WebACL (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments` at transform time. The Reference section MUST capture the ARN field name in the Resource schema excerpt.
- **Append-only stream.** WAF events have no status lifecycle. `REQ-TRF-STS` is N/A. The Silver `status` field is left null.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The Reference section MUST list every action the source emits. This drives the severity-derivation lookup.
- **Log-stream over SDK.** Prefer log-stream consumption over sampled SDK calls. The Quirks fact in the Reference section MUST disclose the chosen mode and justify any deviation.

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

Facts the generate-connector skill needs to emit a WAF connector module. WAF sources emit append-only edge-event records, event records rather than finding records.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md`. Bind one test function per REQ-ID below.

- Bind: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK API (e.g. `GetSampledRequests`). For log-stream consumption (the preferred mode), they are N/A.
- Do NOT bind `REQ-TRF-STS`. WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form. The dedup is event-stream replay-window deduplication, not cross-tool finding overlap. Bind a single test asserting the replay-window behaviour.

### Default severity

`medium`. Severity is **derived**, not source-supplied. There is no `severity` field on a WAF event. The standard severity is computed from `action` (block / allow / count / challenge / captcha) plus rule-group category.

The `src/connectors/{source}/severity.yml` lookup is therefore action-keyed, not severity-keyed. Generate the lookup with action-to-severity mappings covering every documented action value (e.g. `block: high`, `count: low`, `allow: low`, `challenge: medium`). The `mapping.yml` severity field references the lookup with `action` as the source path:

```yaml
severity:
  source_path: action
  lookup: src/connectors/{source}/severity.yml
```

The configurable default for unmatched actions is `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream. Encode in `config.yml`:

- The connector records the last event-time ingested per WebACL or rule group and advances forward on each run.
- For AWS deployments: autoloader-style ingestion from a Firehose-to-S3 prefix or CloudWatch Logs export.
- For on-prem appliances: the same pattern over the forwarded syslog bucket.
- Sampled SDK calls (`GetSampledRequests`) are a **fallback only**. Prefer log-stream consumption: samples lose fidelity under high-volume rules. Where the fallback is used, preserve the statistical sampling weight (`Weight` field) into Bronze for downstream extrapolation.

### Deduplication key

Per the standard mapping: not currently specified for WAF. Append-only event log; cross-tool overlap not yet defined. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a dedup-key tuple for WAF in the current MVP scope.

For replay-window deduplication (within-source, recovering from re-delivered events), the WAF capability scope uses `(timestamp, rule_id, source_ip, request_id)` per the `analyze-source` WAF reference. Encode this tuple in `transform.py` for replay deduplication only:

```python
replay_dedup_key = (row["timestamp"], row["rule_id"], row["source_ip"], row["request_id"])
```

Do NOT emit `dedup_links` rows. The standard `dedup_links` table targets cross-tool finding overlap, which WAF does not participate in. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in a transform-level comment to document the absence.

### Target Silver tables

`silver.waf_events` (plural) per `mkdocs/docs/platform/reference/silver-table-ownership.md` patterns and the WAF capability scope at `mkdocs/docs/connectors/waf/index.md`. The `mapping.yml` block targets `silver.waf_events`, NOT `silver.findings`. This is the headline schema deviation for WAF.

`transform.py` MUST emit a join against `silver.deployments` to resolve the resource ARN associated with the WebACL (ALB, CloudFront distribution, API Gateway stage) into `application_id`. The ARN field is encoded in `mapping.yml` and the connector page Resource schema excerpt documents the field name.

### Authentication norms

Account-scoped, NOT per-tenant:

- **Cloud-native WAFs** (AWS WAF, Cloudflare, Azure Front Door WAF): IAM role or access key bound to the cloud account hosting the WebACLs.
- **On-prem appliances** (F5 ASM, Imperva, ModSecurity): service credential bound to the log-aggregation tier.

`ingest.py` reads credentials via the helper in `src/platform/`; `config.yml` references the secret-scope key names. There is no per-application authentication axis; do not generate one.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt.

- **AWS WAF**: autoloader-style ingestion from the Firehose-to-S3 prefix is the standard pattern. This fits the Lakeflow Connect / SDK envelope.
- **SDK-based sampled-request fallback**: permitted only when full-log ingestion is not yet provisioned. Preserve the sampling weight into Bronze.
- The artefact-collection / autoloader pattern is the dominant WAF mode and aligns with Lakeflow Connect; no CLI-artefact deviation is needed.

### Quirks

- **Event records, not finding records.** Each record is a single edge observation, not a triaged vulnerability. The Silver target is `silver.waf_events`, NOT `silver.findings`. Emit the matching schema in `mapping.yml`. Do not reuse the finding schema.
- **Severity is derived.** Action plus rule-group category drives standard severity through the action-keyed lookup. Generate the lookup as action-keyed. Do NOT generate a severity-keyed lookup that mirrors a source severity field (there is none).
- **Sampling weight preserved.** Where the source returns statistical samples, project the `Weight` field into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** WebACL ARN → `silver.deployments` join at transform time. Encode the ARN field name in `mapping.yml`. Emit the join in `transform.py` (mirrors the structure of the DAST `target` join).
- **Append-only stream.** No status lifecycle; do not project a `status` field; do not generate status-transition code. The `src/connectors/{source}/status.yml` lookup MUST exist (per the every-connector-has-both-files contract) and contain `# N/A: WAF events are append-only; no status lifecycle`.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The severity lookup MUST cover every action the source emits, exhaustive over the documented vocabulary.
- **Log-stream over SDK.** Prefer log-stream consumption. SDK sampled-request mode is fallback-only; document the deviation in a top-of-file comment in `ingest.py` if used.

### Databricks-side production-shape

In addition to the eight-file core, generate-connector emits the **Databricks-side production-shape** for WAF connectors. The skill reads `operational.yml.databricks_runtime` to interpolate the templates.

The WAF `databricks_runtime` schema (reverse-engineered from the AWS WAF follower) covers seventeen fields: `secret_scope`, `bronze_schema`, `bronze_tables`, `envelope_table` (default `event_envelope`), `cron_schedule` (default `0 */15 * * * ?` — every 15 min), `uc_catalog_var`, `job_name` (kebab-case, e.g. `aws-waf-connector`), `default_target`, `default_catalog`, `secret_env_vars` (e.g. `WAF_LOG_BUCKET → waf_log_bucket`, `AWS_WAF_IAM_ROLE_ARN → aws_waf_iam_role_arn`), `extra_install_env_vars` (typically required: `AWS_WAF_ACCOUNT_ID`, `AWS_WAF_LOG_BUCKET_ARN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), `tool_source_label` (kept for cross-category symmetry — `silver.waf_events` is single-source and has no `tool_source` discriminator currently), `entry_wrappers` (`false` — ingest runs in-notebook from `ingest.py`), `ingestion_mode` (`log_stream` or `sdk_sampled`; default `log_stream`), `log_stream_prefix` (default `waf/firehose/`), `firehose_account_id_env` (default `AWS_WAF_ACCOUNT_ID`), `webacl_log_bucket_arn_env` (default `AWS_WAF_LOG_BUCKET_ARN`).

What the production-shape adds on top of the eight-file core:

- **`scripts/load-secrets.sh`** — populates the secret scope from `databricks_runtime.secret_env_vars`. Iterates over the env-var/secret-key pairs and runs `databricks secrets put-secret` per pair.
- **`scripts/install.sh`** — streamlined three-step shape (load-secrets → `databricks bundle run {job_name}` → echo verify). The runbook-grade verify-counts-via-SQL-warehouse flow lives in the docs page, not the install script.
- **Top-level `install.sh`** — orchestrator chaining `runtime/install.sh` → `scripts/load-secrets.sh` → `databricks bundle deploy`. **WAF source-side runtime is mandatory for the log-stream path** — `runtime/install.sh` attaches the Firehose-write S3 bucket policy without which the autoloader has nothing to read.
- **`sql/<envelope>.sql`** — REQUIRED. **`CREATE TABLE`** shape (companion to the autoloader-managed bronze table). Autoloader reads gzipped JSON files from the S3 bucket and lands them with columns `raw_payload`, `webacl_id` (extracted at ingest from `terminatingRuleArn` or `webaclId` for joinability), `ingested_at`, `run_id`. The transform projects this into `silver.waf_events`.
- **No `*_entry.py` wrappers** — `entry_wrappers=false`. The `resources/job.yml` `notebook_path` points at `../ingest.py` directly.
- **`resources/` extras** — alongside `resources/{source}-job.yml` (15-min cron, with an extra `ingestion_mode` job parameter `log_stream | sdk_sampled`), WAF emits `resources/schemas.yml` (bronze only). `resources/connection.yml` is N/A — the workspace AWS service credential reads S3 directly; no UC connection. `resources/pipeline.yml` is N/A — notebook job, not Lakeflow Connect. `resources/volumes.yml` is N/A — the workspace AWS service credential reads from the S3 prefix directly; AWS WAF does not emit a UC Volume.
- **Connector page §4–§7 templates** — §Secrets (table mapping `secret_key` ↔ `env_var` with the workspace-AWS-service-credential note), §Run the job (notebook job named `{job_name}` with the Firehose-buffer-flush callout — Firehose buffers up to 5 minutes or 5 MiB, so smoke tests should generate blockable requests then wait ~5 minutes before the autoloader picks them up on the next 15-min tick), §Verify (Bronze count plus top-terminating-rules sanity check and severity-distribution-by-WebACL aggregation against `silver.waf_events` — note the schema deviation: WAF writes to `silver.waf_events`, NOT `silver.findings`), and §Troubleshooting (no-records-after-buffer-flush, severity-canonical mis-derived from `action`, missing application linkage when the WebACL ARN → `silver.deployments` join did not match).

*Rendered from `.claude/skills/generate-connector/references/waf.md`. Source-of-truth lives in the skill file.*

## validate-implementation: WAF reference

Facts the validate-implementation skill needs to populate the Validation table for a WAF connector. WAF sources emit append-only edge-event records, event records rather than finding records. Status and dedup are N/A; severity is derived from action plus rule-group category.

### Applicable REQ-IDs

From `mkdocs/docs/platform/reference/catalog.md` § "Requirement catalog". The AWS WAF column of the traceability matrix currently reads `N/A` across the board because the source is documented but not built in the MVP. The MVP-built profile would be the set below.

Apply (the test suite MUST have a `@pytest.mark.requirement("REQ-...")`-bound test for each):

- `REQ-ING-AUTH`
- `REQ-ING-HWM`
- `REQ-TRF-MAP`
- `REQ-TRF-SEV`
- `REQ-TRF-TS`
- `REQ-DQ`

Mark `N/A`:

- `REQ-ING-PAG`, N/A: log-stream consumption (the preferred mode per `mkdocs/docs/connectors/waf/index.md` § "Capability scope": "The connector specification SHALL prefer log-stream consumption over sampled SDK calls") has no API pagination. Apply only when the connector consumes a paginated SDK API (e.g. `GetSampledRequests` fallback); otherwise mark `N/A` with the rationale "log-stream mode has no API pagination".
- `REQ-ING-RL`, N/A: same rationale; log-stream consumption has no API rate limit. Apply only when the SDK fallback is in use.
- `REQ-TRF-STS`, N/A: WAF events are append-only block / allow / count records with no lifecycle state. Quoted from `mkdocs/docs/connectors/waf/index.md` § "Capability scope": WAF events are an "append-only" edge-event stream.
- `REQ-DEDUP`, N/A in the standard sense: append-only event stream with no cross-tool overlap. The `mkdocs/docs/platform/reference/canonical-mapping.md` does not list a `dedup_links` tuple for WAF in the current MVP scope. Replay-window deduplication on `(timestamp, rule_id, source_ip, request_id)` is internal to the connector and is asserted under `REQ-DQ`, not `REQ-DEDUP`.

### Default severity

`medium` configurable default; severity is **derived** from `action` plus rule-group category, not source-supplied. Per `mkdocs/docs/connectors/waf/index.md` § "Capability scope": "Severity is not a first-class field on a WAF event; the standard severity is derived from the action and rule-group category per a per-source lookup table." The `REQ-TRF-SEV` test asserts the action-keyed lookup covers every documented action (`block`, `allow`, `count`, `challenge`, `captcha`) and that undocumented actions fall through to `medium` with a data-quality warning.

### Incremental strategy

Timestamp-based HWM over the log stream per `mkdocs/docs/connectors/waf/index.md` § "Capability scope". The connector records the last event-time ingested per WebACL or rule group and advances forward each run. The test suite asserts HWM-resume behaviour under `REQ-ING-HWM` against the timestamp advancement. SDK-fallback mode preserves `Weight` and is also asserted under `REQ-ING-HWM` plus `REQ-TRF-MAP`.

### Deduplication key

Per `mkdocs/docs/platform/reference/canonical-mapping.md`: not currently specified for WAF. Append-only event log; cross-tool overlap not yet defined in MVP scope. `REQ-DEDUP` is N/A.

For replay-window deduplication (within-source, recovering re-delivered events), the connector uses `(timestamp, rule_id, source_ip, request_id)` per `mkdocs/docs/connectors/waf/index.md` § "Capability scope". This is asserted under `REQ-DQ` (a Lakeflow expectation that quarantines duplicate replay events), NOT under `REQ-DEDUP`. The test suite does NOT emit `dedup_links` rows for WAF.

### Target Silver tables

`silver.waf_events` (plural) per the WAF capability scope at `mkdocs/docs/connectors/waf/index.md` and the WAF references in the analyze-source / generate-connector skills. The `REQ-TRF-MAP` test asserts the connector targets `silver.waf_events`, NOT `silver.findings`. This is the headline schema deviation for WAF. The `REQ-TRF-MAP` test additionally verifies the join against `silver.deployments` to resolve the WebACL ARN into `application_id`.

Note: `silver.waf_events` is not listed in `mkdocs/docs/platform/reference/silver-table-ownership.md`. That file enumerates the MVP standard tables, and WAF is documented but not built in the MVP. The plural name follows the pattern of every other entity table on that page (`applications`, `repositories`, `findings`).

### Authentication norms

Account-scoped, NOT per-tenant, per `mkdocs/docs/connectors/waf/index.md` § "Capability scope". Cloud-native WAFs use IAM role or access key; on-prem appliances use a service credential bound to the log-aggregation tier. The test suite asserts credential resolution from the platform secret scope under `REQ-ING-AUTH`.

### Ingestion-tooling preference

Standard order: Lakeflow Connect → Databricks SDK → dlt. Autoloader-style ingestion from the Firehose-to-S3 prefix (AWS WAF) fits the Lakeflow Connect / SDK envelope; no CLI-artefact deviation is needed. The validation suite verifies pagination and rate-limit absence under the N/A markings rather than asserting a tool-choice fact directly.

### Quirks

- **Event records, not finding records.** `REQ-TRF-MAP` asserts the connector targets `silver.waf_events`, not `silver.findings`. The test fails if `silver.findings` rows are emitted.
- **Severity is derived.** `REQ-TRF-SEV` asserts the lookup is action-keyed, not severity-keyed. A severity-keyed lookup that mirrors a source severity field is a `FAIL`.
- **Sampling weight preserved.** Where the SDK sampled-request fallback is in use, `REQ-TRF-MAP` asserts the `Weight` field is projected into Bronze. Downstream extrapolation depends on it.
- **Application linkage via ARN.** `REQ-TRF-MAP` asserts the WebACL ARN → `silver.deployments` join at transform time (mirrors the structure of the DAST `target` join).
- **Append-only stream.** No status lifecycle; `REQ-TRF-STS` is N/A; no `status` field is projected. The `src/connectors/{source}/status.yml` lookup contains `# N/A: WAF events are append-only; no status lifecycle` per the generate-connector WAF reference.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. `REQ-TRF-SEV` asserts coverage over the full action vocabulary the source emits.
- **Log-stream over SDK.** `REQ-ING-PAG` and `REQ-ING-RL` are bound only when the SDK fallback is in use. Log-stream-only deployments mark them `N/A` with the rationale "log-stream mode has no API pagination/rate limit".

*Rendered from `.claude/skills/validate-implementation/references/waf.md`. Source-of-truth lives in the skill file.*
