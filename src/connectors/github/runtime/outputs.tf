output "seed_repo_full_names" {
  description = "Full names (org/repo) of the SAST and DAST target repositories that the framework scans."
  value = [
    data.github_repository.benchmark_java.full_name,
    data.github_repository.benchmark_python.full_name,
    data.github_repository.juice_shop.full_name,
  ]
}

output "sast_repo_full_names" {
  description = "Full names (org/repo) of the SAST target forks (BenchmarkJava and BenchmarkPython)."
  value = [
    data.github_repository.benchmark_java.full_name,
    data.github_repository.benchmark_python.full_name,
  ]
}

output "juice_shop_repo_full_name" {
  description = "Full name (org/repo) of the Juice Shop fork."
  value       = data.github_repository.juice_shop.full_name
}

output "ecr_registry_uri" {
  description = "ECR registry URI for Juice Shop image pushes."
  value       = aws_ecr_repository.juiceshop.repository_url
}

output "github_actions_role_arn" {
  description = "ARN of the IAM role assumed by GitHub Actions via OIDC."
  value       = aws_iam_role.github_actions.arn
}

output "github_actions_role_name" {
  description = "Name of the IAM role assumed by GitHub Actions (for attaching additional policies)."
  value       = aws_iam_role.github_actions.name
}

output "juiceshop_namespace" {
  description = "Kubernetes namespace where Juice Shop runs."
  value       = kubernetes_namespace.juiceshop.metadata[0].name
}

output "juiceshop_ingress_host" {
  description = "External LoadBalancer hostname for Juice Shop (target for ZAP)."
  value       = try(data.kubernetes_service.juiceshop.status[0].load_balancer[0].ingress[0].hostname, "pending")
}
