# analyze-source — WAF reference

Facts the analyze-source skill needs to write a complete Reference section for a WAF source.

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

From `mkdocs/docs/platform/reference/catalog.md`. WAF sources emit edge-event records that are projected into finding-shape rows on `silver.findings`.

- Apply: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (for example sampled-request SDK calls); for log-stream consumption (the preferred mode), these are N/A.
- `REQ-TRF-STS` applies in degraded form — WAF events have no native lifecycle, so the connector emits the literal `open` per the trufflehog convention; `status_canonical` never transitions.
- `REQ-DEDUP` stays N/A on the catalog matrix — WAF events still don't share dedup tuples with SAST/SCA/secrets/DAST. Replay deduplication is achieved via the deterministic `finding_id` hash plus the Bronze→Silver MERGE; no `dedup_links` rows are emitted.

The AWS WAF traceability row currently shows N/A across the matrix because the source is documented but not built in the MVP. The MVP-built profile would be the set above.

## Default severity

`medium`. Severity is not a first-class field on a WAF event; the canonical severity is **derived** from the `action` field via an action-keyed lookup table (e.g. `block→high`, `count→medium`, `allow→low`) — analogous to the secrets convention but data-driven from action rather than fixed.

The Reference section's Enumerations fact MUST disclose the derivation rule (action → canonical severity) and list every documented action value.

## Incremental strategy

Timestamp-based high-water mark over the log stream. Per the WAF capability surface: the connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run.

For AWS deployments the reference pattern is **Firehose to S3** or **CloudWatch Logs into Bronze** via an autoloader-style ingestion. For on-prem appliances the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example `GetSampledRequests`) are supported as a fallback only — the WAF specification requires the connector to PREFER log-stream consumption over sampled SDK calls because samples lose fidelity under high-volume rules.

## Deduplication key

`REQ-DEDUP` is N/A on the catalog matrix — WAF events do not share dedup tuples with SAST/SCA/secrets/DAST findings, so no `dedup_links` rows are emitted. Replay deduplication (recovering from re-delivered events) is achieved instead by the deterministic `finding_id` SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` plus the Bronze→Silver MERGE — re-delivered events collapse onto the same `finding_id` at MERGE time. Cite `mkdocs/docs/platform/reference/canonical-mapping.md` in the Reference section to document the absence of a cross-tool dedup tuple for WAF.

## Target Silver tables

`silver.findings` — the canonical findings table, same target as SAST/SCA/secrets/DAST. WAF events are projected into finding-shape rows: each event becomes one finding row with severity derived from action (via the action-keyed lookup), status set to the literal `open` (no native lifecycle), and a deterministic `finding_id` SHA-256 hashed from `(webacl_arn, request_id, timestamp_ms)`.

WAF events have no native `repository_id`, so `repository_id` is null on the emitted rows. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).

WAF-specific telemetry that is NOT carried on `silver.findings` — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped from the canonical record. Operators query upstream WAF logs (S3 / CloudWatch) for that telemetry.

The headline schema deviation that previously distinguished WAF from other categories has been collapsed: WAF now matches every other category's `silver.findings` target.

## Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs (AWS WAF, Cloudflare, Azure Front Door WAF) authenticate via IAM role or access key bound to the cloud account hosting the WebACLs. On-prem appliances (F5 ASM, Imperva, ModSecurity) authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. For AWS WAF, autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern — this fits the Lakeflow Connect / SDK envelope. SDK-based sampled-request fallback is permitted only when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into Bronze for downstream extrapolation.

## Quirks

- **Finding-shape on `silver.findings`.** WAF now follows the trufflehog convention: each WAF event becomes one finding row on `silver.findings` (the same canonical table SAST/SCA/secrets/DAST target). The previous schema deviation (a dedicated `silver.waf_events` table) has been collapsed.
- **Severity is derived.** Severity comes from the `action` field via an action-keyed lookup (`block→high`, `count→medium`, `allow→low`, etc.). The lookup is action-keyed, not severity-keyed.
- **Status is the literal `open`.** WAF events have no native lifecycle; the connector follows the trufflehog convention and writes the literal `open` to `status_canonical`. `status_canonical` never transitions.
- **Deterministic `finding_id`.** Each row's `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)`. Re-deliveries collapse at MERGE time.
- **WAF-only telemetry is dropped.** `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself are NOT carried on `silver.findings`. Operators query upstream WAF logs (S3 / CloudWatch) for that detail.
- **Sampling weight.** Where the source returns statistical samples (sampled SDK calls), each record carries a sampling weight that MUST be preserved into Bronze for downstream extrapolation (it is not projected onto `silver.findings`).
- **Application linkage is deferred.** WAF events have no native `repository_id`; `repository_id` is null on emitted rows. Gold-side aggregations bucket WAF findings under the `__UNMAPPED__` application sentinel until an operator extends `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping (out of scope for the MVP).
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The Reference section MUST list every action the source emits — this drives the severity-derivation lookup.
- **Log-stream over SDK.** Prefer log-stream consumption over sampled SDK calls; the Reference section's Quirks fact MUST disclose the chosen mode and justify any deviation.

## Lakeflow Connect availability

No source in the waf category appears in the analyze-source LFC managed-source catalogue today. Resolution: category-canonical default applies — `artifact_path` for the canonical autoloader-from-S3 / Firehose log-stream pattern documented under "## Ingestion-tooling preference" above; otherwise the Maintained Python SDK catalogue applies (see below).

## Maintained Python SDK availability

**AWS WAF** → `ingestion_path: sdk` with `python_sdk_module: boto3` per the analyze-source Maintained Python SDK catalogue. boto3 is the first-party AWS SDK (`boto3.client('wafv2')` covers the WAF endpoints — `GetSampledRequests`, `ListWebACLs`, `GetLoggingConfiguration` — and handles auth, paging, and retry via the library's standard mechanisms).

The `sdk` branch applies to the SDK-based sampled-request mode and any boto3-driven WAF read path. The `artifact_path` branch remains the canonical mode for autoloader-from-S3 / Firehose log-stream consumption (per "## Ingestion-tooling preference" above).
