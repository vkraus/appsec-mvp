output "sonarqube_url" {
  description = "External LoadBalancer URL where SonarQube responds. Feed this into the SonarQube connector's `SONARQUBE_URL` secret."
  value       = "http://${try(data.kubernetes_service.sonarqube.status[0].load_balancer[0].ingress[0].hostname, "pending")}:9000"
}

output "sonarqube_namespace" {
  description = "Kubernetes namespace where the SonarQube Helm release is installed."
  value       = kubernetes_namespace.sonarqube.metadata[0].name
}

output "sonarqube_db_secret_name" {
  description = "Name of the kubernetes secret holding SonarQube's JDBC credentials (for debug: `kubectl get secret -n sonarqube <name>`)."
  value       = kubernetes_secret.sonarqube_db.metadata[0].name
}

output "sonarqube_project_token" {
  description = "Long-lived random opaque value emitted as the project analysis token. Register it with SonarQube post-install (the chart does not support declarative token creation) and surface to the cross-scanner CI workflow."
  value       = random_password.sonarqube_token.result
  sensitive   = true
}

output "rds_endpoint" {
  description = "Postgres endpoint SonarQube uses (host:port). Either the RDS instance this module created or the `var.rds_endpoint` operator-supplied value."
  value       = local.rds_endpoint_resolved
}

output "rds_db_name" {
  description = "Postgres database name SonarQube uses."
  value       = local.rds_db_name_resolved
}

output "rds_username" {
  description = "Postgres username SonarQube uses."
  value       = local.rds_username_resolved
}

output "rds_password" {
  description = "Postgres password SonarQube uses (generated random when this module created RDS, else the operator-supplied `var.rds_password`)."
  value       = local.rds_password_resolved
  sensitive   = true
}
