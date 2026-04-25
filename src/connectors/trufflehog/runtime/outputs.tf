output "bronze_schema_full_name" {
  description = "Three-level name of the TruffleHog Bronze schema (`<catalog>.bronze_trufflehog`). Useful as input to downstream wiring (autoloader pipelines, Bronze→Silver jobs)."
  value       = "${var.catalog}.bronze_trufflehog"
}

output "volume_path" {
  description = "Filesystem-style path of the UC Volume (`/Volumes/<catalog>/bronze_trufflehog/artefacts`) — the location autoloader / `spark.read.json` should point at."
  value       = var.trufflehog_artifact_volume_path
}

output "volume_full_name" {
  description = "Three-level name of the UC Volume (`<catalog>.bronze_trufflehog.artefacts`). Use this in `GRANT` statements and Lakeflow Volume references."
  value       = "${databricks_volume.trufflehog_artefacts.catalog_name}.${databricks_volume.trufflehog_artefacts.schema_name}.${databricks_volume.trufflehog_artefacts.name}"
}
