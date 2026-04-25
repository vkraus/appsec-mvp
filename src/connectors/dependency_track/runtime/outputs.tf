output "bronze_schema_full_name" {
  description = "Fully qualified Unity Catalog name of the Dependency-Track Bronze schema (catalog.schema). Feed into the connector job's catalog/schema variables."
  value       = "${var.catalog}.bronze_dependency_track"
}

output "dependency_track_host" {
  description = "Dependency-Track instance host (FQDN, no protocol) — echoed back so downstream wiring can pick it up from `terraform output` rather than re-reading the tfvars."
  value       = var.dependency_track_host
}

output "dependency_track_apikey_secret_scope" {
  description = "Databricks secret scope holding the Dependency-Track API key (echoed for parity with the input variable, useful for downstream `databricks secrets get-secret` calls)."
  value       = var.dependency_track_apikey_secret_scope
}

output "dependency_track_apikey_secret_key" {
  description = "Secret-key under the scope holding the Dependency-Track API key (echoed for parity with the input variable)."
  value       = var.dependency_track_apikey_secret_key
}
