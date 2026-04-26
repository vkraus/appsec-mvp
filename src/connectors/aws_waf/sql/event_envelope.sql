-- Bronze envelope for AWS WAF log records.
-- Autoloader reads gzipped JSON files from the S3 bucket and lands them
-- here for the WAF transform to project into silver.findings (canonical
-- finding-shape; was previously silver.waf_events, collapsed).

CREATE TABLE IF NOT EXISTS ${catalog}.bronze_aws_waf.event_envelope (
  raw_payload STRING,
  webacl_id STRING,        -- terminatingRuleArn or webaclId, extracted at ingest for joinability
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT 'Raw AWS WAF log records; transformed into silver.findings as finding-shape rows (severity from action; status literal open; rule_id_native from terminatingRuleId).';
