-- Bronze envelope overlay for ServiceNow business_applications.
--
-- Lakeflow Connect owns the physical bronze schema. This view projects
-- the section 2.2.2 envelope on top of it so downstream readers see the
-- uniform metadata alongside source-native columns.
--
-- The Lakeflow ingestion metadata columns (_rescued_data, and the
-- snapshot/sync timestamps populated by the ingestion pipeline) are
-- the source of truth for _ingestion_timestamp and _batch_id. Verify
-- the column names against the deployed pipeline before merging: the
-- Lakeflow column names vary by connector version. If they differ,
-- update the CAST and aliases here rather than the pipeline config.

CREATE OR REPLACE VIEW ${catalog}.bronze_servicenow.business_applications_envelope AS
SELECT
  CAST(_sync_timestamp AS TIMESTAMP) AS _ingestion_timestamp,
  'servicenow' AS _source_system,
  _sync_run_id AS _batch_id,
  to_json(struct(*)) AS _raw_payload,
  CAST(_sync_timestamp AS STRING) AS _hwm_value,
  *
FROM ${catalog}.bronze_servicenow.business_applications;
