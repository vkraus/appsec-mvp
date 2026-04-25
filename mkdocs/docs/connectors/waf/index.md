# WAF connectors

WAF connectors ingest edge-layer block and allow events from web application firewalls.

!!! note "SCM-first dependency"
    Connectors in this category depend on at least one SCM connector being
    installed first. Their findings resolve to applications via the resource
    ARN associated with the WebACL, then to repositories via `silver.app_repo_mapping`
    and `silver.repositories` populated by SCM. Walk the
    [SCM category](../scm/index.md) before installing a WAF connector.

## Capability scope

WAF sources emit event records rather than finding records. Each record describes a single request observed at the edge, keyed by `(timestamp, rule_id, source_ip, request_id)`. A single record carries the matched rule identifier, the action taken (block, allow, count, challenge, captcha), the source IP and optional geo-IP, request metadata (method, URI, headers), and a sampling weight where the provider returns statistical samples rather than the full stream. Severity is not a first-class field on a WAF event. The standard severity is derived from the action and rule-group category per a per-source lookup table, similar to the severity-derivation pattern used for secrets.

WAF deployment styles split between cloud-native edge services (AWS WAF, Cloudflare, Azure Front Door WAF) and on-prem appliances (F5 ASM, Imperva, ModSecurity behind a reverse proxy). Cloud-native services expose request samples via their control-plane SDK and stream full logs to an object store or managed log service (CloudWatch Logs, Firehose to S3, Cloud Logging). On-prem appliances expose a syslog or forwarded-log feed into the log-aggregation tier of the deployment. The connector specification **SHALL** prefer log-stream consumption over sampled SDK calls where both are available, because sampled SDK calls lose fidelity under high-volume rules.

The incremental strategy is timestamp-based high-water mark over the log stream. The connector records the last event-time ingested per WebACL or rule group and advances the window forward on each run. For AWS deployments, the reference pattern is Firehose to S3 or CloudWatch Logs into Databricks bronze via an autoloader-style ingestion. For on-prem appliances, the same pattern applies over the forwarded syslog bucket. Sampled SDK calls (for example, `GetSampledRequests`) are supported as a fallback when full-log ingestion is not yet provisioned, with the statistical sampling weight preserved into bronze for downstream extrapolation.

Authentication is account-scoped rather than per-tenant. Cloud-native WAFs authenticate via IAM role or access key bound to the cloud account hosting the WebACLs, and on-prem appliances authenticate via a service credential bound to the log-aggregation tier. There is no per-application authentication axis. Application scoping is derived at transform time from the resource ARNs associated with the WebACL (ALB, CloudFront distribution, API Gateway stage) joined against `silver.deployments`.

## Canonical mapping contribution

WAF sources populate the Silver `waf_event` table scoped by `(application_id, rule_id, timestamp)`. See [Canonical mapping](../../platform/reference/canonical-mapping.md).

## Skills

Three skills cover the connector lifecycle for WAF sources, with category-specific facts at [Skills](skills.md). The procedural body of each skill is documented at [Connector skills](../../platform/reference/connector-skills.md).

## Connectors in this category

- [AWS WAF](aws-waf.md): intended integration (no MVP implementation).
