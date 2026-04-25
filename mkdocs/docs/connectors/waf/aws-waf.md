# AWS WAF

## Overview

AWS WAF is the reference runtime-security source, representing the third detection tier (distinct from static and dynamic testing). Each record is **event-shaped, not finding-shaped**: a single request observed at the edge with a WAF action attached, not a triaged vulnerability. Records populate `silver.waf_events`, linked to applications through the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments` at transform time.

The WAF reference profile prefers **log-stream consumption** (CloudWatch Logs / Kinesis Data Firehose / S3) over the WAFv2 SDK's `GetSampledRequests` action, because samples lose fidelity under high-volume rules. The SDK path is documented as a fallback for deployments where full-log delivery is not yet provisioned; in that mode, the per-record `Weight` field MUST be preserved into Bronze for downstream extrapolation.

**Category:** WAF (runtime, edge event stream) · **Integration pattern:** log-stream autoloader (preferred) / SDK boto3 (fallback)

!!! info "Not in MVP scope"
    A reference AWS WAF connector is not part of the MVP. The
    Reference section below documents the intended integration per
    the WAF capability surface (`mkdocs/docs/connectors/waf/index.md`)
    and the analyze-source WAF reference. The traceability matrix in
    `mkdocs/docs/platform/reference/catalog.md` shows N/A across
    every REQ for AWS WAF for this reason.

## Prerequisites

!!! info "Not implemented in MVP"
    A reference AWS WAF connector is not part of the MVP. The
    Reference section below documents the intended integration per
    the category capability surface; follow the WAF skills
    to generate a connector when needed.

## Reference

### API surface

AWS WAF exposes two complementary surfaces, and the reference profile uses both — log-stream consumption as the primary path and the WAFv2 SDK as a fallback for the same WebACLs.

**Log-stream surface (preferred).** AWS WAF emits a per-request log record for every WebACL that has logging enabled. Logging destinations are Amazon CloudWatch Logs log groups, Amazon S3 prefixes, or Amazon Kinesis Data Firehose delivery streams; for high-volume ingestion the canonical pattern is **Firehose to S3** consumed by an autoloader-style Bronze ingestion. No WAF-API authentication is involved on this path: the connector reads from the destination using the IAM role attached to the Databricks workspace's AWS service credential, with permissions scoped to the destination prefix or log group.

**SDK surface (fallback).** AWS WAFv2 also exposes a REST API accessed through the AWS SDK (boto3 for the Python reference implementation). Primary action for the connector: `GetSampledRequests`, returning up to 500 sample requests for a specified rule within a time window of at most three hours. Supporting actions: `ListWebACLs`, `GetWebACL`, and `ListRuleGroups` enumerate the rule inventory. Authentication uses AWS IAM credentials resolved through the standard AWS credential chain; the reference implementation uses an IAM role assumed from the Databricks workspace's AWS service credential. Required IAM actions: `wafv2:GetSampledRequests`, `wafv2:ListWebACLs`, `wafv2:GetWebACL`, `wafv2:ListRuleGroups`. CloudFront-scoped WebACLs require the `us-east-1` regional endpoint; regional WebACLs use the resource's home region.

The category authentication norm is account-scoped, not per-tenant: a single IAM principal covers every WebACL hosted in the account, regardless of which application the WebACL fronts. There is no per-application authentication axis.

### Pagination and rate limits

Behaviour differs by surface, and the applicability of `REQ-ING-PAG` / `REQ-ING-RL` is conditional on which surface the deployment uses.

**Log-stream surface.** No pagination concept; ingestion is autoloader-style over the Firehose-to-S3 prefix (or equivalent CloudWatch Logs subscription). Throughput is bounded by the Bronze autoloader's configured concurrency rather than by an API quota. `REQ-ING-PAG` and `REQ-ING-RL` are **N/A** in this mode per the WAF analyze-source reference.

**SDK surface.** `GetSampledRequests` does not paginate: it returns up to `MaxItems` samples (cap 500) per call, with sampling applied server-side when matched traffic exceeds the underlying 5,000-request first-pass. The connector issues one call per (WebACL, rule, time-window) tuple. AWS API throttling follows the standard AWS account-level throttling model; the connector applies exponential backoff on `ThrottlingException` per the connector-abstraction specification. In this mode `REQ-ING-PAG` collapses to a single-page contract and `REQ-ING-RL` covers the throttling-retry behaviour.

### Incremental hook

Timestamp-based high-water mark over the log stream. The connector records the maximum event-time ingested per WebACL (or per rule group, when scoping is finer) and advances the window forward on each run. WAF events are append-only and have no lifecycle state, so there is no `updated_at` field to track and no equivalent for `REQ-TRF-STS`.

On the **log-stream surface**, the autoloader picks up newly arrived files in the Firehose-to-S3 prefix; the high-water mark is the max `timestamp` observed in Bronze and is used for restart-from-checkpoint semantics rather than as a server-side filter. On the **SDK fallback**, the connector parameterises `GetSampledRequests` with a bounded `TimeWindow` (`StartTime`, `EndTime`) and records the last `EndTime` per (WebACL, rule). Successive runs advance the window forward; the AWS-imposed three-hour ceiling on `TimeWindow` is the inner-loop limit.

### Resource schema excerpt

Two record shapes apply, one per surface; the connector lands them in distinct Bronze tables and reconciles them onto the same `silver.waf_events` shape at transform time.

**WAF log record (log-stream surface) — consumed fields.**

| Field | Type | Meaning |
|---|---|---|
| `timestamp` | number (epoch ms) | Event time at the edge; normalised to UTC datetime in Silver. |
| `webaclId` | string (ARN) | WebACL ARN; joined against `silver.deployments` via the WebACL's associated resource ARN to derive `application_id`. |
| `terminatingRuleId` | string | Identifier of the rule that finalised the action; used as `rule_id` in `silver.waf_events`. |
| `terminatingRuleType` | string | Rule type (`REGULAR`, `RATE_BASED`, `GROUP`, `MANAGED_RULE_GROUP`); feeds the severity-derivation lookup alongside `action`. |
| `action` | string | Final action: `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. |
| `httpRequest.clientIp` | string | Source IP observed by the WAF; component of the dedup key. |
| `httpRequest.country` | string | Two-letter country code from geo-IP. |
| `httpRequest.uri` | string | Request path; participates in the application-linkage join. |
| `httpRequest.httpMethod` | string | HTTP method. |
| `httpRequest.requestId` | string | Edge-assigned request identifier; component of the dedup key. |
| `httpRequest.headers` | list | Header name/value pairs observed on the request. |
| `ruleGroupList` | list | Rule groups evaluated and the per-group terminating action; used for severity derivation when `terminatingRuleType = GROUP`. |
| `labels` | list | WAF labels emitted by matching rules; used for downstream classification. |
| `responseCodeSent` | integer | HTTP status returned to the client (present when the action did not allow upstream). |

**`SampledHTTPRequest` (SDK fallback) — consumed fields.**

| Field | Type | Meaning |
|---|---|---|
| `Timestamp` | datetime | Event time; normalised to UTC at the Bronze-to-Silver transform. |
| `Request.ClientIP` | string | Source IP observed by the WAF; component of the dedup key. |
| `Request.Country` | string | Two-letter country code from geo-IP. |
| `Request.URI` | string | Request path. |
| `Request.Method` | string | HTTP method. |
| `Request.Headers` | list | Header name/value pairs observed on the request. |
| `Weight` | integer | Sampling weight; the event represents `Weight` underlying requests. Preserved into Bronze for downstream extrapolation. |
| `Action` | string | WAF action: `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. |
| `RuleNameWithinRuleGroup` | string | Matched rule; used as `rule_id` in `silver.waf_events`. |
| `ResponseCodeSent` | integer | HTTP status returned to the client. |
| `Labels` | list | WAF labels emitted by the matching rule. |
| `OverriddenAction` | string | Action overridden by the surrounding rule group; recorded for audit when present. |

The Silver scope key for `silver.waf_events` is `(application_id, rule_id, timestamp)`. The replay-window deduplication tuple is `(timestamp, rule_id, source_ip, request_id)` per the WAF capability surface. Application scoping is derived at transform time from the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments`.

### Enumerations

**Action.** Documented values are `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE` (consistent across both surfaces; the SDK renders them upper-case, log records render `action` upper-case as well). The reference profile ingests every value, including `ALLOW`, into Bronze; whether `ALLOW` rows project into Silver is a per-deployment policy switch.

**Severity is derived, not sourced.** WAF events carry no severity field. The canonical severity is computed from `(action, terminatingRuleType / rule-group category)` per a per-source lookup table at `config/severity/aws-waf.yml`. The reference derivation:

- `BLOCK` on a managed-rule-group match → `high`.
- `BLOCK` on a custom regular or rate-based rule → `medium`.
- `COUNT` on a managed-rule-group match → `medium`.
- `CAPTCHA` / `CHALLENGE` → `low`.
- `ALLOW` → not ingested by default; if ingested, `low`.

The lookup MUST cover every documented action; undocumented values fall through to the configured default (`medium`) and trigger a data-quality warning per `REQ-TRF-SEV`. The lookup is action-keyed (with rule-type as a secondary axis), not severity-keyed — because there is no source severity to translate.

**Status.** WAF events are append-only and have no lifecycle. `REQ-TRF-STS` is **N/A** for this source. The Silver `status` column is left null.

### Quirks

- **Event-shaped, not finding-shaped.** Each record describes a single edge observation, not a triaged vulnerability. The Silver target is `silver.waf_events`, **not** `silver.findings`. `generate-connector` MUST emit the matching schema in `mapping.yml`; the finding shape is not reused.
- **Severity is derived.** Severity comes from `(action, rule-group category / rule type)`, not from a source field. The lookup table at `config/severity/aws-waf.yml` is action-keyed.
- **Sampling weight (SDK fallback).** When `GetSampledRequests` returns statistical samples, each record carries a `Weight` representing the number of underlying requests it stands in for. `Weight` MUST be preserved into Bronze for downstream extrapolation; gold-layer aggregations multiply by `Weight` to estimate true volume.
- **Application linkage via ARN.** Application scoping uses the WebACL's associated resource ARN (ALB, CloudFront distribution, API Gateway stage), captured as `webaclId` on log records, joined against `silver.deployments` at transform time. Without an active deployment row, events fall through unlinked and surface in the data-quality unmatched bucket.
- **Append-only stream.** WAF events have no status lifecycle. `REQ-TRF-STS` is N/A. The Silver `status` field is left null and the connector emits no status-transition events.
- **Action vocabulary.** Documented actions are `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. `OverriddenAction` (SDK) and the `ruleGroupList` per-group action (log records) capture rule-group-level overrides — the reference connector logs but does not re-derive severity from these.
- **Log-stream over SDK.** The reference profile prefers log-stream consumption. The SDK path (`GetSampledRequests`) is permitted only as a fallback when full-log delivery is not yet provisioned; the chosen mode MUST be recorded in the connector's `config.yml` so that REQ-applicability can be evaluated correctly.
- **CloudFront endpoint constraint (SDK only).** CloudFront-scoped WebACLs require the `us-east-1` regional endpoint regardless of where the Databricks workspace runs; regional WebACLs use the resource's home region. The connector enumerates both scopes when iterating over `ListWebACLs`.

## Setup

!!! info "Not implemented in MVP"
    See the Prerequisites admonition above.

## Validation

!!! info "Not implemented in MVP"
    See the Prerequisites admonition above.

## Generation log

This connector page is produced by the connector-lifecycle skills. The Generation log table records the skill runs that produce the page, the connector module, and the validation report.

| Stage              | Skill                              | Inputs                                                                                              | Outputs                                                                            | Run on     | Skills repo ref                          |
|--------------------|------------------------------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|------------|------------------------------------------|
| Source analysis    | `analyze-source` (waf)             | name=AWS WAF; url=https://docs.aws.amazon.com/waf/latest/APIReference/Welcome.html; category=waf    | mkdocs/docs/connectors/waf/aws-waf.md §1–§3                                        | 2026-04-25 | d47eb26 (retrofit-9-connectors)          |
| Module generation  | `generate-connector` (waf)         | (pending)                                                                                           | (pending)                                                                          | (pending)  | (pending)                                |
| Validation         | `validate-implementation` (waf)    | (pending)                                                                                           | (pending)                                                                          | (pending)  | (pending)                                |
