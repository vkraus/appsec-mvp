output "catalog_name" {
  value = databricks_catalog.mvp.name
}

output "artifacts_volume" {
  value = "/Volumes/${databricks_catalog.mvp.name}/${databricks_schema.bronze.name}/${databricks_volume.artifacts.name}"
}

output "connectors_secret_scope" { value = databricks_secret_scope.connectors.name }
output "servicenow_pipeline_id" { value = databricks_pipeline.servicenow.id }
output "connector_job_ids" { value = { for k, j in databricks_job.connector : k => j.id } }
