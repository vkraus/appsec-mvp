-- Bronze envelope for TruffleHog scan artefacts.
--
-- Autoloader reads line-delimited JSON files from the UC Volume
-- (`<catalog>.bronze_trufflehog.artefacts`) and lands them here. The
-- secrets transform (`src/connectors/trufflehog/transform.py`) projects
-- this table into silver.findings, dropping the `Raw` / `RawV2` fields
-- per the references/secrets.md redaction rule.
--
-- The table name `findings` matches the `bronze_table` configured in
-- `src/connectors/trufflehog/config.yml` and the literal default in
-- `ingest.run_ingest_pipeline` — keep all three in sync if renamed.

CREATE TABLE IF NOT EXISTS ${catalog}.bronze_trufflehog.findings (
  raw_payload STRING,
  artefact_path STRING,
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT 'TruffleHog scan JSON; transformed into silver.findings (secrets).';
