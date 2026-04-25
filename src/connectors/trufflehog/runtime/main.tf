# ---------------------------------------------------------------------------
# UC Volume for TruffleHog scan artefacts.
#
# Operator provisions the underlying cloud bucket (S3 / ADLS / GCS) where
# CI/CD runners drop TruffleHog `--json` output. This terraform creates the
# Unity Catalog Volume that maps to it for autoloader-style ingestion into
# `bronze_trufflehog.findings`.
#
# The `bronze_trufflehog` schema itself is declared by the connector's
# Databricks Asset Bundle (see `src/connectors/trufflehog/resources/
# schemas.yml`); this runtime only adds the Volume on top.
# ---------------------------------------------------------------------------

resource "databricks_volume" "trufflehog_artefacts" {
  catalog_name     = var.catalog
  schema_name      = "bronze_trufflehog"
  name             = "artefacts"
  volume_type      = "EXTERNAL"
  storage_location = var.trufflehog_artifact_volume_path
  comment          = "TruffleHog scan JSON artefacts dropped by CI/CD; ingested into bronze_trufflehog.findings via autoloader."
}
