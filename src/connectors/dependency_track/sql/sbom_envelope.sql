-- Bronze envelope for Dependency-Track findings.
-- Stores raw vulnerability JSON from /api/v1/finding/project/{uuid};
-- transformed to silver.findings (category="sca") via the SCA mapping.
--
-- Companion table to ${catalog}.bronze_dependency_track.findings (the
-- dlt-managed flattened bronze table referenced from
-- src/connectors/dependency_track/ingest.py and config.yml). The envelope
-- preserves the section 2.2.2 raw_payload + run_id + ingested_at metadata
-- so downstream consumers can replay the original API response without
-- re-fetching from Dependency-Track.

CREATE TABLE IF NOT EXISTS ${catalog}.bronze_dependency_track.findings_envelope (
  raw_payload STRING,        -- raw JSON from API
  vuln_id_native STRING,     -- vulnerability.vulnId, extracted for joinability
  attributed_on STRING,      -- ISO timestamp from attribution.attributedOn
  ingested_at TIMESTAMP,
  run_id STRING
)
USING DELTA
COMMENT 'Raw Dependency-Track finding records; transformed into silver.findings (sca).';
