"""AWS WAF connector (WAF category).

Runtime-security source projecting WAF log records as finding-shape rows
into ``silver.findings`` (canonical; was previously the dedicated
``silver.waf_events``, collapsed for schema uniformity). Severity is
DERIVED from the WAF action (block / count / challenge / captcha / allow);
status is the literal ``open`` (matches the trufflehog convention for
sources without a native lifecycle).

Ingestion path: log-stream autoloader from a Firehose-to-S3 prefix
(CloudWatch Logs / Kinesis Data Firehose / S3); the WAFv2 SDK
``GetSampledRequests`` action is retained as a fallback for deployments
where full-log delivery is not yet provisioned.

See ``mkdocs/docs/connectors/waf/aws-waf.md`` for the reference profile.
"""
