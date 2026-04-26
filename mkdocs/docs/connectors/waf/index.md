# WAF connectors

WAF connectors ingest edge-layer block and allow events from web application firewalls and project each event as one finding row on the canonical `silver.findings` table.

!!! note "SCM-first dependency"
    Connectors in this category depend on at least one SCM connector being
    installed first so that `silver.repositories` is populated upstream.
    WAF events have no native repository linkage — `repository_id` is null
    on every emitted row, and Gold-side aggregations bucket WAF findings
    under the `__UNMAPPED__` application sentinel until an operator extends
    `silver.app_repo_mapping` with a `webacl_arn → application_id` mapping
    (out of scope for the MVP). Walk the [SCM category](../scm/index.md)
    before installing a WAF connector.

## Capability scope

WAF sources emit per-request edge observations: for each WebACL evaluation, one record carries the matched rule identifier, the action taken (block, allow, count, challenge, captcha), the source IP and optional geo-IP, request metadata (method, URI, headers), and a sampling weight where the provider returns statistical samples rather than the full stream. Severity is not a first-class field on a WAF event; the canonical severity is **derived** from the action via an action-keyed lookup table — analogous to the secrets convention but data-driven from action rather than fixed.

Each WAF event projects to one finding row on `silver.findings` (the same canonical target as SAST, SCA, secret, and DAST connectors) per the trufflehog convention for sources without a native lifecycle. Status is the literal `open` and never transitions. The `finding_id` is a deterministic SHA-256 hash of `(webacl_arn, request_id, timestamp_ms)` so re-delivered events collapse at the Bronze-to-Silver MERGE. WAF telemetry beyond the canonical projection — `source_ip`, `country`, `http_method`, `response_code`, `sampling_weight`, `rule_type`, and the `action` value itself — is intentionally dropped. Operators query the upstream WAF logs (S3 / CloudWatch) directly when they need that detail. The schema deviation that previously distinguished WAF (a dedicated `silver.waf_events` table) has been collapsed; WAF now matches every other category's `silver.findings` target.

WAF deployment styles split between cloud-native edge services (AWS WAF, Cloudflare, Azure Front Door WAF) and on-prem appliances (F5 ASM, Imperva, ModSecurity behind a reverse proxy). Cloud-native services expose request samples via their control-plane SDK and stream full logs to an object store or managed log service (CloudWatch Logs, Firehose to S3, Cloud Logging). On-prem appliances expose a syslog or forwarded-log feed into the log-aggregation tier of the deployment. The connector specification **SHALL** prefer log-stream consumption over sampled SDK calls where both are available, because sampled SDK calls lose fidelity under high-volume rules.

The incremental strategy is timestamp-based high-water mark over the log stream. The connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run. For AWS deployments, the reference pattern is Firehose to S3 or CloudWatch Logs into Databricks bronze via an autoloader-style ingestion. For on-prem appliances, the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example, `GetSampledRequests`) are supported as a fallback when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into bronze for downstream extrapolation (it is not projected onto `silver.findings`).

Authentication is account-scoped rather than per-tenant. Cloud-native WAFs authenticate via IAM role or access key bound to the cloud account hosting the WebACLs, and on-prem appliances authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis.

## Canonical mapping contribution

WAF sources populate the canonical `silver.findings` table with one row per edge event, discriminated by `category = "waf"` and `tool_source = "aws_waf"`. See [Canonical mapping](../../platform/reference/canonical-mapping.md) for the per-field projection (severity from action, status literal `open`, deterministic `finding_id`, dropped telemetry).

## Skills

Four skills cover the connector lifecycle for WAF sources, with category-specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [AWS WAF](aws-waf.md): intended integration (no MVP implementation).
