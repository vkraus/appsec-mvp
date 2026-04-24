output "sonarqube_url" {
  value = "http://${data.kubernetes_service.sonarqube.status[0].load_balancer[0].ingress[0].hostname}:9000"
}

output "sonarqube_project_token" {
  value     = random_password.sonarqube_token.result
  sensitive = true
}

output "zap_url" {
  value = "http://${data.kubernetes_service.zap.status[0].load_balancer[0].ingress[0].hostname}:8080"
}

output "zap_api_key" {
  value     = random_password.zap_api_key.result
  sensitive = true
}

output "juiceshop_namespace" { value = kubernetes_namespace.juiceshop.metadata[0].name }

output "juiceshop_ingress_host" {
  value = try(data.kubernetes_service.juiceshop.status[0].load_balancer[0].ingress[0].hostname, "pending")
}
