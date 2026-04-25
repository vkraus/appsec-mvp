# AWS WAF

!!! info "Placeholder — not implemented in MVP"
    A reference AWS WAF connector is not part of the MVP. This page is a
    scaffolding placeholder framing the intended runbook structure; the
    Reference section below documents the integration per the category
    capability surface. Follow the [WAF skills](skills.md) to generate the
    connector when needed.

## What this connector ingests

AWS WAF is the reference runtime-security source, representing the third detection tier (distinct from static and dynamic testing). Operational pattern: **runtime telemetry with time-window sampled retrieval** — the connector issues `GetSampledRequests` on a fixed cadence for each rule and WebACL, retrieving matched-request samples over a bounded event-time window. Findings populate `silver.waf_events`, linked to applications through the associated resource ARN (ALB, CloudFront distribution, API Gateway stage) and AWS resource tags.

*The per-source specification below is scaffolded from the AWS API reference and is intended for refinement by an `analyze-source` run against a provisioned AWS account. Fields marked* `VERIFY` *require confirmation against a live WebACL.*

**Category:** WAF (runtime, time-window sampled retrieval) · **Integration pattern:** SDK (boto3)

## Dependencies

- **Depends on: platform set up (Phase 1 complete).** Catalog, `mvp-connectors` secret scope, and the `silver` schema must exist. See [Setup platform](../../platform/index.md).
- **Depends on: at least one SCM connector installed and run, so that `silver.repositories` is populated.** WAF events resolve to applications through the associated resource ARN, then to repositories via `silver.app_repo`. The chain requires an SCM connector to populate `silver.repositories` upstream.

## Reference

### API surface

AWS WAFv2 exposes a REST API accessed through the AWS SDK (boto3 for the Python reference implementation). Primary action for the connector: `GetSampledRequests`, returning up to 5,000 sample requests for a specified rule within a time window of at most three hours. Supporting actions: `ListWebACLs`, `GetWebACL`, and `ListRuleGroups` enumerate the rule inventory. Authentication uses AWS IAM credentials resolved through the standard AWS credential chain; the reference implementation uses an IAM role assumed from the Databricks workspace's AWS service credential. Required IAM actions: `wafv2:GetSampledRequests`, `wafv2:ListWebACLs`, `wafv2:GetWebACL`.

### Pagination and rate limits

`GetSampledRequests` does not paginate: it returns up to `MaxItems` samples (cap 500) per call, with sampling applied server-side when matched traffic exceeds the cap. The connector issues one call per (rule, WebACL, time-window) tuple. AWS API throttling follows the standard AWS account-level throttling model; the reference implementation uses exponential backoff on `ThrottlingException` per the connector-abstraction specification.

### Incremental hook

No high-water-mark column exists. The connector parameterises `GetSampledRequests` with a bounded `TimeWindow` (`StartTime`, `EndTime`) and records the last end-time per (WebACL, rule) in the HWM state table. Successive runs advance the window forward. Window size is deployment-tunable; the reference implementation defaults to 15-minute windows invoked every 15 minutes, chosen to balance sampling-density loss against API call volume.

### Resource schema excerpt

AWS WAF `SampledHTTPRequest` fields consumed by the connector:

| Field | Type | Meaning |
|---|---|---|
| `Timestamp` | datetime | Event time; normalised to UTC at the Bronze-to-Silver transform. |
| `Request.ClientIP` | string | Source IP observed by the WAF. |
| `Request.Country` | string | Two-letter country code from geo-IP. |
| `Request.URI` | string | Request path; joins to `silver.deployments` via host+path. |
| `Request.Method` | string | HTTP method. |
| `Request.Headers` | list | Header name/value pairs observed on the request. |
| `Weight` | integer | Sampling weight; the event represents `Weight` underlying requests. |
| `Action` | string | WAF action taken: `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. |
| `RuleNameWithinRuleGroup` | string | Matched rule; used as `rule_id` in `silver.waf_events`. |
| `ResponseCodeSent` | integer | HTTP status returned to client (present when action did not allow upstream). |
| `Labels` | list | WAF labels emitted by the matching rule; used for downstream classification. |

### Enumerations

**Action.** `ALLOW`, `BLOCK`, `COUNT`, `CAPTCHA`, `CHALLENGE`. No severity field; the canonical severity is derived: `BLOCK` on a managed-rule match→`high`; `COUNT` on a managed-rule match→`medium`; `CAPTCHA`/`CHALLENGE`→`low`; `ALLOW` is not ingested by default. The derivation table is in `src/connectors/aws_waf/severity.yml`.

### Quirks

**Event-shaped, not finding-shaped.** WAF events describe attempted exploitation attempts against live traffic, not discrete vulnerabilities. The framework treats them as findings-with-weight: each record is a `silver.waf_events` row, and aggregations in the gold layer summarise attack patterns per application (peak block rate, unique source IPs, rule-match distribution) rather than enumerating events individually.

**Sampling is lossy by design.** `GetSampledRequests` caps returned samples; for high-volume rules, the returned set is a statistical sample. The `Weight` field records the extrapolation factor. Gold-layer aggregations use `Weight` to estimate total counts; deployments requiring full fidelity should additionally enable CloudWatch Logs for the WebACL and ingest the log stream as a parallel Bronze source.

## Setup

!!! info "Not implemented in MVP"
    See the Prerequisites admonition above.

## Validation

!!! info "Not implemented in MVP"
    See the Prerequisites admonition above.
