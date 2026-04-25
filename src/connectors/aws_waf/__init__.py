"""AWS WAF connector (WAF category).

Event-shaped runtime-security source. Records populate ``silver.waf_events``
via a log-stream autoloader pattern (CloudWatch Logs / Kinesis Data Firehose
/ S3); the WAFv2 SDK ``GetSampledRequests`` action is retained as a fallback
for deployments where full-log delivery is not yet provisioned.

See ``mkdocs/docs/connectors/waf/aws-waf.md`` for the reference profile.
"""
