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

From `mkdocs/docs/platform/reference/catalog.md`. WAF sources emit edge-event records treated as findings.

- Apply: `REQ-ING-AUTH`, `REQ-ING-HWM`, `REQ-TRF-MAP`, `REQ-TRF-SEV`, `REQ-TRF-TS`, `REQ-DQ`.
- `REQ-ING-PAG` and `REQ-ING-RL` apply only when the connector consumes a paginated SDK surface (for example sampled-request SDK calls); for log-stream consumption (the preferred mode), these are N/A.
- `REQ-TRF-STS` does not apply — WAF events are append-only block / allow / count records with no lifecycle state.
- `REQ-DEDUP` applies in degraded form — deduplication is event-stream deduplication (replay-window) rather than cross-tool finding overlap.

The AWS WAF traceability row currently shows N/A across the matrix because the source is documented but not built in the MVP. The MVP-built profile would be the set above.

## Default severity

`medium`. Severity is not a first-class field on a WAF event; the canonical severity is **derived** from the action and rule-group category per a per-source lookup table — analogous to the secrets convention but data-driven from action+rule rather than fixed.

The Reference section's Enumerations fact MUST disclose the derivation rule (action + rule-group category → canonical severity) and list every documented action value.

## Incremental strategy

Timestamp-based high-water mark over the log stream. Per the WAF capability surface: the connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run.

For AWS deployments the reference pattern is **Firehose to S3** or **CloudWatch Logs into Bronze** via an autoloader-style ingestion. For on-prem appliances the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example `GetSampledRequests`) are supported as a fallback only — the WAF specification requires the connector to PREFER log-stream consumption over sampled SDK calls because samples lose fidelity under high-volume rules.

## Deduplication key

`(timestamp, rule_id, source_ip, request_id)` per the WAF capability surface, with the Silver event scope `(application_id, rule_id, timestamp)` per `mkdocs/docs/platform/reference/canonical-mapping.md`. Because WAF records are append-only event-shaped data rather than finding-shaped, dedup is replay-window deduplication on the unique tuple, not cross-tool overlap linking.

## Target Silver tables

`silver.waf_events` per the WAF capability surface. Application scoping is derived at transform time from the WebACL's associated resource ARNs (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments`. The Reference section MUST disclose this transform-time join.

## Authentication norms

Account-scoped, NOT per-tenant. Cloud-native WAFs (AWS WAF, Cloudflare, Azure Front Door WAF) authenticate via IAM role or access key bound to the cloud account hosting the WebACLs. On-prem appliances (F5 ASM, Imperva, ModSecurity) authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

## Ingestion-tooling preference

Standard preference order applies: Lakeflow Connect > Databricks SDK > dlt. For AWS WAF, autoloader-style ingestion from the Firehose-to-S3 prefix is the canonical pattern — this fits the Lakeflow Connect / SDK envelope. SDK-based sampled-request fallback is permitted only when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into Bronze for downstream extrapolation.

## Quirks

- **Event-shaped, not finding-shaped.** Each record describes a single request observed at the edge, not a triaged vulnerability. The Silver target is `silver.waf_events`, not `silver.findings`. The Reference section's Quirks fact MUST disclose this so generate-connector emits the right schema.
- **Severity is derived.** Severity comes from action + rule-group category, not from a source field. The lookup table is action-keyed, not severity-keyed.
- **Sampling weight.** Where the source returns statistical samples (sampled SDK calls), each record carries a sampling weight that MUST be preserved into Bronze for downstream extrapolation.
- **Application linkage via ARN.** Application scoping uses the WebACL's associated resource ARNs (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments` at transform time. The Reference section MUST capture the ARN field name in the Resource schema excerpt.
- **Append-only stream.** WAF events have no status lifecycle. `REQ-TRF-STS` is N/A. The Silver `status` field is left null.
- **Action vocabulary.** Documented actions include `block`, `allow`, `count`, `challenge`, `captcha`. The Reference section MUST list every action the source emits — this drives the severity-derivation lookup.
- **Log-stream over SDK.** Prefer log-stream consumption over sampled SDK calls; the Reference section's Quirks fact MUST disclose the chosen mode and justify any deviation.

## Lakeflow Connect availability

No source in the waf category appears in the analyze-source LFC managed-source catalogue today. Resolution: category-canonical default applies — `sdk_dlt` for REST/SDK sources (the standard ingestion-tooling preference for this category).
