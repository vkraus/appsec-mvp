output "databricks_workspace_url" {
  value = var.databricks_workspace_url
}

output "sonarqube_url" {
  value = module.scanners_eks.sonarqube_url
}

output "zap_url" {
  value = module.scanners_eks.zap_url
}

output "github_org" {
  value = var.github_org
}

output "servicenow_instance_url" {
  value = var.servicenow_instance_url
}

output "semgrep_artifact_bucket" {
  value = module.aws_foundation.artifact_bucket
}

output "ecr_registry_uri" {
  value = module.aws_foundation.ecr_registry_uri
}

output "juiceshop_namespace" {
  value = module.scanners_eks.juiceshop_namespace
}

output "juiceshop_ingress_host" {
  value = module.scanners_eks.juiceshop_ingress_host
}
