# AWS WAF

## What this connector ingests

AWS WAF is the reference runtime-security source, representing the third detection tier (distinct from static and dynamic testing). The connector projects each WAF edge event as one finding row on the canonical `silver.findings` table — same target as every other scanner category. Severity is derived from the WAF `action` (block, count, challenge, captcha, allow) via an action-keyed lookup; status is the literal `open` and never transitions (matching the trufflehog convention for sources without a native lifecycle); and `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` so re-delivered events collapse at the Bronze-to-Silver MERGE.

The WAF reference profile prefers **log-stream consumption** (CloudWatch Logs / Kinesis Data Firehose / S3) over the `GetSampledRequests` action of the WAFv2 SDK, because samples lose fidelity under high-volume rules. The SDK path is documented as a fallback for deployments where full-log delivery is not yet provisioned. In that mode, the per-record `Weight` field MUST be preserved into Bronze for downstream extrapolation (it is not projected onto `silver.findings`).

WAF telemetry beyond severity, rule_id, and url — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped from the canonical record. Operators query the upstream WAF logs (S3 / CloudWatch) when they need that detail.

**Category:** WAF (runtime, edge event stream) · **Integration pattern:** log-stream autoloader (preferred) / SDK boto3 (fallback)

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md).
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** WAF events have no native `repository_id`; `repository_id` is null on emitted rows. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).

## User inputs

AWS WAF projects each Bronze edge log record (one request observed at the WebACL with an action attached) onto one row of the canonical `silver.findings` table. The reference profile ingests via S3 autoloader over Firehose-delivered logs, so the runbook below assumes the log-stream path. The SDK fallback is a separate code path documented in Reference; it is not covered in this install runbook.

| Input | Where to obtain | Used as |
|---|---|---|
| AWS account ID | The dev account ID hosting the WebACL. Find via `aws sts get-caller-identity --query Account --output text`. | Env var `AWS_WAF_ACCOUNT_ID`; terraform var `aws_waf_account_id`. |
| AWS region | The WebACL region. CloudFront-scoped WebACLs are always `us-east-1`; regional WebACLs match the application's region. | Env var `AWS_REGION`; terraform var `aws_region`. |
| WAF log S3 bucket ARN | Pre-existing bucket where Firehose drops logs. Create one with `aws s3 mb s3://my-waf-logs-bucket` (the connector does not create the bucket — it only attaches a write policy for the Firehose service principal). | Env var `AWS_WAF_LOG_BUCKET_ARN` (e.g. `arn:aws:s3:::my-waf-logs-bucket`); terraform var `aws_waf_log_bucket_arn`; secret-scope key `waf_log_bucket`. |
| Configured WebACL with logging enabled | An AWS WAFv2 WebACL with at least one rule (`AWSManagedRulesCommonRuleSet` is a good starter) and **logging configured** to deliver to a Kinesis Data Firehose stream that writes to the S3 bucket above. The WebACL, the Firehose stream, and the S3 bucket are operator prerequisites — the connector does not provision them. See the AWS docs at <https://docs.aws.amazon.com/waf/latest/developerguide/logging.html> for the wiring. The optional source runtime below automates the S3 bucket policy step. | Operator standup; the connector reads the bucket. |
| AWS access keys for the log-bucket reader | IAM user with `s3:GetObject` and `s3:ListBucket` on the log bucket. Programmatic access key + secret pair. | Env vars `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`; secret-scope key `aws_waf_iam_role_arn` is also populated by `load-secrets.sh` for the SDK fallback path. |

!!! warning "Log-stream mode only in this runbook"
    The instructions below are scoped to `ingestion_mode: log_stream` (the default in `src/connectors/aws_waf/config.yml`). Operators on the `sdk_sampled` fallback should use the SDK-credential variant in Reference instead — they need a `wafv2:GetSampledRequests` IAM principal rather than an S3 reader.

## Optional source runtime

`src/connectors/aws_waf/runtime/` is a Terraform module that wires an **operator-supplied** S3 bucket into the connector. Specifically it:

- References (does **not** create) the bucket at `var.aws_waf_log_bucket_arn`.
- Attaches `aws_s3_bucket_policy.waf_logs_firehose` granting the `firehose.amazonaws.com` service principal `s3:PutObject` and `s3:PutObjectAcl`, conditioned on `aws:SourceAccount = var.aws_waf_account_id`.
- Outputs `bronze_schema_full_name` (`${catalog}.bronze_aws_waf`) and an echo of `s3_bucket_arn` for downstream wiring.

It does **not** provision the WebACL, the Firehose delivery stream, or the S3 bucket itself — those are operator prerequisites (see the AWS WAF logging docs linked above). Operators with an existing bucket policy that already allows Firehose writes can skip the runtime entirely and just supply the bucket ARN to the connector via secrets.

Apply (from repo root) once the prerequisites are in place:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
cd src/connectors/aws_waf/runtime
terraform init
terraform apply \
  -var="catalog=appsec_dev" \
  -var="aws_region=us-east-1" \
  -var="aws_waf_account_id=000000000000" \
  -var="aws_waf_log_bucket_arn=arn:aws:s3:::my-waf-logs-bucket"
```

## Secrets

Loaded into the `mvp-connectors` secret scope by `src/connectors/aws_waf/scripts/load-secrets.sh`:

| Secret key | Source env var | Purpose |
|---|---|---|
| `waf_log_bucket` | `WAF_LOG_BUCKET` | S3 bucket name the autoloader reads Firehose-delivered logs from. |
| `aws_waf_iam_role_arn` | `AWS_WAF_IAM_ROLE_ARN` | IAM role ARN used by the SDK fallback (`GetSampledRequests`). Populated even in log-stream mode so the connector can switch modes without rerunning the loader. |

The Databricks workspace's AWS service credential (configured at platform setup) is what the autoloader uses to read S3. The IAM access keys exported below are read by `load-secrets.sh` and any direct boto3 calls; they should map to a principal with `s3:GetObject` + `s3:ListBucket` on the log bucket.

Run from repo root after Phase 1 completes:

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export WAF_LOG_BUCKET="my-waf-logs-bucket"
export AWS_WAF_IAM_ROLE_ARN="arn:aws:iam::000000000000:role/appsec-mvp-waf-reader"
bash src/connectors/aws_waf/scripts/load-secrets.sh
# Expected: OK: aws_waf secrets loaded into scope mvp-connectors
```

## Reference

### API scope

AWS WAF exposes two complementary APIs, and the reference profile uses both: log-stream consumption as the primary path and the WAFv2 SDK as a fallback for the same WebACLs.

**Log-stream API (preferred).** AWS WAF emits a per-request log record for every WebACL that has logging enabled. Logging destinations are Amazon CloudWatch Logs log groups, Amazon S3 prefixes, or Amazon Kinesis Data Firehose delivery streams. For high-volume ingestion the recommended pattern is **Firehose to S3** consumed by an autoloader-style Bronze ingestion. No WAF-API authentication is involved on this path. The connector reads from the destination using the IAM role attached to the AWS service credential of the Databricks workspace, with permissions scoped to the destination prefix or log group.

**SDK API (fallback).** AWS WAFv2 also exposes a REST API accessed through the AWS SDK (boto3 for the Python reference implementation). Primary action for the connector: `GetSampledRequests`, returning up to 500 sample requests for a specified rule within a time window of at most three hours. Supporting actions: `ListWebACLs`, `GetWebACL`, and `ListRuleGroups` enumerate the rule inventory. Authentication uses AWS IAM credentials resolved through the standard AWS credential chain. The reference implementation uses an IAM role assumed from the AWS service credential of the Databricks workspace. Required IAM actions: `wafv2:GetSampledRequests`, `wafv2:ListWebACLs`, `wafv2:GetWebACL`, `wafv2:ListRuleGroups`. CloudFront-scoped WebACLs require the `us-east-1` regional endpoint. Regional WebACLs use the home region of the resource.

The category authentication norm is account-scoped, not per-tenant: a single IAM principal covers every WebACL hosted in the account, regardless of which application the WebACL fronts. There is no per-application authentication axis.

### Pagination and rate limits

Behaviour differs by API, and the applicability of `REQ-ING-PAG` / `REQ-ING-RL` is conditional on which API the deployment uses.

**Log-stream API.** No pagination concept. Ingestion is autoloader-style over the Firehose-to-S3 prefix (or equivalent CloudWatch Logs subscription). Throughput is bounded by the configured concurrency of the Bronze autoloader rather than by an API quota. `REQ-ING-PAG` and `REQ-ING-RL` are **N/A** in this mode per the WAF analyze-source reference.

**SDK API.** `GetSampledRequests` does not paginate: it returns up to `MaxItems` samples (cap 500) per call, with sampling applied server-side when matched traffic exceeds the underlying 5,000-request first-pass. The connector issues one call per (WebACL, rule, time-window) tuple. AWS API throttling follows the standard AWS account-level throttling model. The connector applies exponential backoff on `ThrottlingException` per the connector-abstraction specification. In this mode `REQ-ING-PAG` collapses to a single-page contract and `REQ-ING-RL` covers the throttling-retry behaviour.

### Incremental hook

Timestamp-based high-water mark over the log stream. The connector records the maximum event-time ingested per WebACL (or per rule group, when scoping is finer) and advances the window forward on each run. WAF events have no native lifecycle state, so there is no `updated_at` field to track; `silver.findings.status_canonical` is the literal `open` on every row (matching the trufflehog convention) and `REQ-TRF-STS` is N/A in the catalog matrix for the same reason it is N/A on the trufflehog row.

On the **log-stream API**, the autoloader picks up newly arrived files in the Firehose-to-S3 prefix. The high-water mark is the max `timestamp` observed in Bronze and is used for restart-from-checkpoint semantics rather than as a server-side filter. On the **SDK fallback**, the connector parameterises `GetSampledRequests` with a bounded `TimeWindow` (`StartTime`, `EndTime`) and records the last `EndTime` per (WebACL, rule). Successive runs advance the window forward. The AWS-imposed three-hour ceiling on `TimeWindow` is the inner-loop limit.

### Resource schema excerpt

Two record structures apply, one per API. The connector lands them in distinct Bronze tables and reconciles them onto the canonical `silver.findings` schema at transform time.

**WAF log record (log-stream API), consumed fields.**

| Field | Type | Meaning |
|---|---|---|
| `timestamp` | number (epoch ms) | Event time at the edge; normalised to UTC datetime as `silver.findings.first_seen_at` and `last_seen_at`. Also a component of the `finding_id` hash. |
| `webaclId` | string (ARN) | WebACL ARN; component of the `finding_id` hash. WAF events have no native `repository_id`, so `silver.findings.repository_id` is null on every emitted row. |
| `terminatingRuleId` | string | Identifier of the rule that finalised the action; populates `silver.findings.rule_id_native`. |
| `terminatingRuleType` | string | Rule type (`REGULAR`, `RATE_BASED`, `GROUP`, `MANAGED_RULE_GROUP`); not projected onto `silver.findings`. |
| `action` | string | Final action: `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. Drives `silver.findings.severity_canonical` via the action-keyed lookup at `src/connectors/aws_waf/severity.yml`. The `action` value itself is not projected onto `silver.findings`. |
| `httpRequest.clientIp` | string | Source IP observed by the WAF; not projected onto `silver.findings`. |
| `httpRequest.country` | string | Two-letter country code from geo-IP; not projected. |
| `httpRequest.uri` | string | Request path; populates `silver.findings.url` (the closest finding-shape "location" for an edge event). |
| `httpRequest.httpMethod` | string | HTTP method; not projected. |
| `httpRequest.requestId` | string | Edge-assigned request identifier; component of the `finding_id` hash. |
| `httpRequest.headers` | list | Header name/value pairs observed on the request; not projected. |
| `ruleGroupList` | list | Rule groups evaluated and the per-group terminating action; not projected. |
| `labels` | list | WAF labels emitted by matching rules; not projected. |
| `responseCodeSent` | integer | HTTP status returned to the client; not projected. |

**`SampledHTTPRequest` (SDK fallback), consumed fields.**

| Field | Type | Meaning |
|---|---|---|
| `Timestamp` | datetime | Event time; normalised to UTC at the Bronze-to-Silver transform; populates `first_seen_at` / `last_seen_at` and feeds the `finding_id` hash. |
| `Request.ClientIP` | string | Source IP observed by the WAF; not projected onto `silver.findings`. |
| `Request.Country` | string | Two-letter country code from geo-IP; not projected. |
| `Request.URI` | string | Request path; populates `silver.findings.url`. |
| `Request.Method` | string | HTTP method; not projected. |
| `Request.Headers` | list | Header name/value pairs observed on the request; not projected. |
| `Weight` | integer | Sampling weight; the event represents `Weight` underlying requests. Preserved into Bronze for downstream extrapolation; not projected onto `silver.findings`. |
| `Action` | string | WAF action: `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. Drives `severity_canonical` via the action-keyed lookup. |
| `RuleNameWithinRuleGroup` | string | Matched rule; populates `silver.findings.rule_id_native`. |
| `ResponseCodeSent` | integer | HTTP status returned to the client; not projected. |
| `Labels` | list | WAF labels emitted by the matching rule; not projected. |
| `OverriddenAction` | string | Action overridden by the surrounding rule group; not projected. |

**Projection onto `silver.findings`.**

| `silver.findings` column | Source / derivation |
|---|---|
| `finding_id` | SHA-256 hash of `(webaclId, httpRequest.requestId, timestamp)` — deterministic, so re-delivered events collapse onto the same row at MERGE. |
| `tool_source` | Literal `"aws_waf"`. |
| `category` | Literal `"waf"`. |
| `severity_canonical` | Derived from `action` via the action-keyed lookup at `src/connectors/aws_waf/severity.yml` (`block→high`, `count→medium`, `challenge→low`, `captcha→low`, `allow→low`). |
| `status_canonical` | Literal `"open"` (no native lifecycle; matches the trufflehog convention). |
| `rule_id_native` | `terminatingRuleId` (log record) or `RuleNameWithinRuleGroup` (SDK). |
| `url` | `httpRequest.uri` (log record) or `Request.URI` (SDK). |
| `first_seen_at` / `last_seen_at` | `timestamp` (epoch ms → UTC datetime) or `Timestamp` (datetime). |
| `repository_id` | Null on every row (WAF events have no native repository linkage). |
| `cwe_id` / `cve_id` / `file_path` / `start_line` | Null. |

WAF telemetry beyond this projection (`source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself) is intentionally dropped from the canonical record. Operators query the upstream WAF logs (S3 prefix or CloudWatch) directly when they need that detail. The previous schema deviation (a dedicated `silver.waf_events` table with this telemetry attached) has been collapsed; WAF now matches every other category's `silver.findings` target.

### Enumerations

**Action.** `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. No severity field on the source. Canonical severity is derived from the action via the action-keyed lookup at `src/connectors/aws_waf/severity.yml`:

- `BLOCK` → `high`.
- `COUNT` → `medium`.
- `CHALLENGE` → `low`.
- `CAPTCHA` → `low`.
- `ALLOW` → `low`.

The lookup MUST cover every documented action; undocumented values fall through to the configured default (`medium`) and trigger a data-quality warning per `REQ-TRF-SEV`. The lookup is action-keyed, not severity-keyed, because there is no source severity to translate.

**Status.** WAF events have no native lifecycle. The connector writes the literal `open` to `silver.findings.status_canonical` (matching the trufflehog convention for sources without a native lifecycle); the field never transitions. `REQ-TRF-STS` is marked **N/A** in the catalog matrix for the same reason it is N/A on the trufflehog row: literal-status sources have no transitions to validate.

### Quirks

- **Finding-shape on `silver.findings`.** Each WAF event projects to one row on the canonical `silver.findings` table — same target as SAST, SCA, secret, and DAST connectors. The previous schema deviation (a dedicated `silver.waf_events` table) has been collapsed; the connector reuses the canonical envelope columns, with `cwe_id`/`cve_id`/`repository_id`/`file_path`/`start_line` null.
- **Severity is derived.** Severity comes from the `action` field, not from a source severity. The lookup table at `src/connectors/aws_waf/severity.yml` is action-keyed.
- **Status is the literal `open`.** Per the trufflehog convention, `status_canonical = "open"` on every emitted row; the field never transitions. `src/connectors/aws_waf/status.yml` carries the literal as the `default` row.
- **Deterministic `finding_id`.** `finding_id` is a SHA-256 hash of `(webaclId, httpRequest.requestId, timestamp)`. Re-delivered events from the upstream Firehose / CloudWatch path collapse onto the same row at the Bronze-to-Silver MERGE.
- **WAF-only telemetry is dropped.** `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself are NOT projected onto `silver.findings`. Operators query the upstream WAF logs (S3 prefix or CloudWatch) directly when they need that detail.
- **Sampling weight (SDK fallback).** When `GetSampledRequests` returns statistical samples, each record carries a `Weight` representing the number of underlying requests it stands in for. `Weight` MUST be preserved into Bronze for downstream extrapolation; it is not projected onto `silver.findings`.
- **Application linkage is deferred.** WAF events have no native `repository_id`; `silver.findings.repository_id` is null on every emitted row. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP). The connector does not emit a transform-time join against `silver.deployments`.
- **Action vocabulary.** Documented actions are `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. `OverriddenAction` (SDK) and the `ruleGroupList` per-group action (log records) capture rule-group-level overrides; the reference connector logs but does not re-derive severity from these.
- **Log-stream over SDK.** The reference profile prefers log-stream consumption. The SDK path (`GetSampledRequests`) is permitted only as a fallback when full-log delivery is not yet provisioned. The chosen mode MUST be recorded in `config.yml` for the connector so that REQ-applicability can be evaluated correctly.
- **CloudFront endpoint constraint (SDK only).** CloudFront-scoped WebACLs require the `us-east-1` regional endpoint regardless of where the Databricks workspace runs. Regional WebACLs use the home region of the resource. The connector enumerates both scopes when iterating over `ListWebACLs`.

## Run the job

The AWS WAF ingestion is a notebook job named `aws-waf-connector` (declared in `src/connectors/aws_waf/resources/job.yml`) that runs every 15 minutes once enabled. Trigger an on-demand run:

```bash
databricks bundle run aws-waf-connector --target dev
```

Wait time depends on traffic volume. For a smoke test, generate a few blockable requests against the WebACL-fronted distribution:

```bash
for i in {1..5}; do
  curl "https://your-cloudfront-distribution.cloudfront.net/?id=' OR 1=1--"
done
```

Then wait ~5 minutes for Firehose to flush the buffered batch to S3 (Firehose buffers up to 5 minutes or 5 MiB, whichever comes first) before the autoloader picks the records up on the next 15-minute pipeline tick.

Alternatively, the orchestrator script runs `load-secrets.sh` and triggers the bundle in one shot:

```bash
bash src/connectors/aws_waf/scripts/install.sh
```

**Normalization spot check.**

- Raw `action = "BLOCK"` → silver `severity_canonical = 'high'`.
- Raw `action = "COUNT"` → silver `severity_canonical = 'medium'`.
- Raw `action = "CHALLENGE"` or `"CAPTCHA"` or `"ALLOW"` → silver `severity_canonical = 'low'`.

## Verify

```sql
-- Bronze: raw WAF log envelopes landed by the autoloader.
SELECT count(*) FROM appsec_dev.bronze_aws_waf.event_envelope;

-- Top terminating rules across WAF findings on the canonical findings table.
SELECT rule_id_native, count(*)
  FROM appsec_dev.silver.findings
  WHERE tool_source = 'aws_waf'
  GROUP BY rule_id_native
  ORDER BY 2 DESC
  LIMIT 10;

-- Severity distribution for WAF findings — confirms the action-keyed
-- severity lookup is firing correctly.
SELECT severity_canonical, count(*)
  FROM appsec_dev.silver.findings
  WHERE tool_source = 'aws_waf'
  GROUP BY severity_canonical;
```

Expected: bronze count > 0 after the Firehose buffer flushes; silver rows on `silver.findings` filtered by `tool_source = 'aws_waf'`; `rule_id_native` populated from the WAF log envelope's `terminatingRuleId`; `severity_canonical` derived from `action` (`BLOCK` → `high`, `COUNT` → `medium`, `CHALLENGE` / `CAPTCHA` / `ALLOW` → `low`); `status_canonical` is the literal `open` on every row; `repository_id` is null on every row (Gold-side aggregations bucket the rows under the `__UNMAPPED__` application sentinel).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Bronze table empty after a successful job run | The Firehose buffer has not flushed yet (up to 5 minutes), or log delivery is not configured. Verify the bucket has objects with `aws s3 ls s3://your-bucket/AWSLogs/ --recursive`. If the bucket is empty, recheck the WebACL logging configuration in the AWS console. |
| `AccessDenied` on S3 read in the job log | The IAM principal behind `AWS_ACCESS_KEY_ID` is missing `s3:GetObject` (or `s3:ListBucket`) on the log bucket. Update the IAM policy, then re-run `bash src/connectors/aws_waf/scripts/load-secrets.sh` and re-deploy the bundle. |
| All `severity_canonical` values land on `medium` | The action-keyed lookup at `src/connectors/aws_waf/severity.yml` fell through to the default for an unknown `action`. Inspect the actual values landing in bronze: `SELECT DISTINCT raw_payload:action FROM appsec_dev.bronze_aws_waf.event_envelope` and add the missing key to `severity.yml`. |
| Firehose objects present but no rows in bronze | Autoloader has not picked up the prefix yet. Confirm the connector's `log_stream.prefix` in `src/connectors/aws_waf/config.yml` (default `waf/firehose/`) matches the actual S3 layout, and trigger another run. |
| Bronze rows present but `silver.findings` shows no `tool_source = 'aws_waf'` rows | The Bronze→Silver transform has not run, or `MERGE` collapsed re-deliveries onto an existing `finding_id`. Check the silver row count first (`SELECT count(*) FROM appsec_dev.silver.findings WHERE tool_source = 'aws_waf'`); the `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)`, so re-deliveries collapse onto the same row by design. |

## Validation

### Implementation report

| Requirement | Bound test | Outcome |
|---|---|---|
| `REQ-ING-AUTH` | `src/connectors/aws_waf/tests/test_ingest.py::test_ingest_contract_rejects_missing_aws_credential_ref` | PASS |
| `REQ-ING-PAG` | n/a | N/A |
| `REQ-ING-RL` | n/a | N/A |
| `REQ-ING-HWM` | `src/connectors/aws_waf/tests/test_ingest.py::test_event_timestamp_hwm_round_trip` | PASS |
| `REQ-TRF-MAP` | `src/connectors/aws_waf/tests/test_transform.py::test_normalise_event_projects_log_record_onto_silver_findings_shape` | PASS |
| `REQ-TRF-SEV` | `src/connectors/aws_waf/tests/test_transform.py::test_severity_lookup_covers_every_documented_action_value` | PASS |
| `REQ-TRF-STS` | n/a | N/A |
| `REQ-TRF-TS` | `src/connectors/aws_waf/tests/test_transform.py::test_epoch_ms_timestamp_normalises_to_utc_datetime` | PASS |
| `REQ-DQ` | `src/connectors/aws_waf/tests/test_transform.py::test_required_columns_are_non_null_on_every_valid_record` | PASS |
| `REQ-DEDUP` | n/a | N/A |

Collected 6 requirement-bound applicable REQs via `pytest src/connectors/aws_waf/tests/ -v --tb=short` (2026-04-25, 0.41 s wall-clock); 25 passed, 0 failed, 5 skipped; 6 applicable REQs PASS, 4 marked N/A. N/A rationale: `REQ-ING-PAG` and `REQ-ING-RL`: log-stream mode has no API pagination or rate limit (SDK fallback is single-page `GetSampledRequests` with boto3-native throttling). `REQ-TRF-STS`: WAF events have no native lifecycle; `silver.findings.status_canonical` is the literal `open` on every row (matching the trufflehog convention) and never transitions, so the catalog matrix marks the requirement N/A as it does for the trufflehog row. `REQ-DEDUP`: WAF rows do not share dedup tuples with SAST/SCA/secrets/DAST findings, so no `dedup_links` rows are emitted; replay deduplication (re-delivered events) is achieved by the deterministic `finding_id` SHA-256 hash collapsing onto the same row at the Bronze→Silver MERGE, asserted under `REQ-DQ` rather than `REQ-DEDUP`.

### Tests

Tests live under [`src/connectors/aws_waf/tests/`](https://github.com/vkraus/appsec-mvp/tree/main/src/connectors/aws_waf/tests). The report table above is the per-REQ outcome.

## Implementation log

This connector page is produced by the connector-lifecycle skills. The Implementation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                                              | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (waf)             | name=AWS WAF; url=https://docs.aws.amazon.com/waf/latest/APIReference/Welcome.html; category=waf    | mkdocs/docs/connectors/waf/aws-waf.md sections 1 to 3                              | 2026-04-25 | b7c1b7c (retrofit-9-connectors)          |
| Source provisioning | `provision-source` (waf)          | source_runtime fields=runtime_provisioner, catalog_var_name, bronze_schema_name, aws_region_var_name, aws_region_default, aws_account_id_var_name, log_bucket_arn_var_name, firehose_service_principal, firehose_actions, bucket_policy_sid, secret_keys_external, sample_artefact_path, terraform_required_version | src/connectors/aws_waf/runtime/, mkdocs/docs/connectors/waf/aws-waf.md §Source provisioning | 2026-04-25 | 05db254 (split-source-and-databricks-skills) |
| Module generation  | `generate-connector` (waf)         | page hash=920adf25fea2; databricks_runtime fields=secret_scope, bronze_schema, bronze_tables, envelope_table, cron_schedule, uc_catalog_var, job_name, default_target, default_catalog, secret_env_vars, extra_install_env_vars, tool_source_label, entry_wrappers, ingestion_mode, log_stream_prefix, firehose_account_id_env, webacl_log_bucket_arn_env | src/connectors/aws_waf/__init__.py, src/connectors/aws_waf/config.yml, src/connectors/aws_waf/ingest.py, src/connectors/aws_waf/transform.py, src/connectors/aws_waf/mapping.yml, src/connectors/aws_waf/severity.yml, src/connectors/aws_waf/status.yml, src/connectors/aws_waf/tests/, src/connectors/aws_waf/scripts/install.sh, src/connectors/aws_waf/scripts/load-secrets.sh, src/connectors/aws_waf/sql/event_envelope.sql, src/connectors/aws_waf/resources/job.yml, src/connectors/aws_waf/resources/schemas.yml, mkdocs/docs/connectors/waf/aws-waf.md §4–§7 | 2026-04-25 | 05db254 (split-source-and-databricks-skills) |
| Validation         | `validate-implementation` (waf)    | module path=src/connectors/aws_waf/                                                                 | mkdocs/docs/connectors/waf/aws-waf.md §5                                           | 2026-04-25 | b0d6c1b (retrofit-9-connectors)          |
