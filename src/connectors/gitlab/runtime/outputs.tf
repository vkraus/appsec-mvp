output "bronze_schema_full_name" {
  description = "Fully-qualified Bronze schema name (catalog.schema). Downstream bundle jobs reference this as the ingestion target."
  value       = "${var.catalog}.bronze_gitlab"
}

output "gitlab_host" {
  description = "GitLab tenant host, echoed for downstream bundle resolution."
  value       = var.gitlab_host
}
