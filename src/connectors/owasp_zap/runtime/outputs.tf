output "zap_namespace" {
  description = "Kubernetes namespace where ZAP runs."
  value       = kubernetes_namespace.zap.metadata[0].name
}

output "zap_url" {
  description = "Public URL where the ZAP daemon API responds. Feed this into the OWASP ZAP connector's ZAP_URL secret. On first apply the LoadBalancer hostname may still be unresolved — re-run `terraform apply` (or `terraform refresh`) once AWS provisions the ELB to populate it."
  value       = "http://${try(data.kubernetes_service.zap.status[0].load_balancer[0].ingress[0].hostname, "pending")}:${var.service_port}"
}

output "zap_api_key" {
  description = "API key for authenticating to the ZAP daemon. Sensitive."
  value       = random_password.zap_api_key.result
  sensitive   = true
}

output "zap_api_key_secret_name" {
  description = "Name of the kubernetes secret holding the ZAP API key (env var `ZAP_API_KEY`). Useful for `kubectl -n <ns> get secret <name>` debugging."
  value       = kubernetes_secret.zap_api_key.metadata[0].name
}
