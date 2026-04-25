output "seed_repo_names" {
  description = "List of seeded GitHub repository full names (org/repo)."
  value = concat(
    [for r in github_repository.seed : r.full_name],
    [github_repository.juiceshop.full_name]
  )
}

output "sast_seed_repo_names" {
  description = "Seeded SAST/SCA target repositories (deliberately-vulnerable fixtures)."
  value       = [for r in github_repository.seed : r.full_name]
}

output "juiceshop_repo_full_name" {
  description = "Full name (org/repo) of the seeded Juice Shop fork."
  value       = github_repository.juiceshop.full_name
}

output "ecr_registry_uri" {
  description = "ECR registry URI for Juice Shop image pushes."
  value       = aws_ecr_repository.juiceshop.repository_url
}

output "github_actions_role_arn" {
  description = "ARN of the IAM role assumed by GitHub Actions via OIDC."
  value       = aws_iam_role.github_actions.arn
}

output "juiceshop_namespace" {
  description = "Kubernetes namespace where Juice Shop runs."
  value       = kubernetes_namespace.juiceshop.metadata[0].name
}

output "juiceshop_ingress_host" {
  description = "External LoadBalancer hostname for Juice Shop (target for ZAP)."
  value       = try(data.kubernetes_service.juiceshop.status[0].load_balancer[0].ingress[0].hostname, "pending")
}
