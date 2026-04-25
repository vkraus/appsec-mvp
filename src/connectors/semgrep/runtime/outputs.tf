output "semgrep_namespace" {
  description = "Kubernetes namespace where the Semgrep CronJob runs."
  value       = kubernetes_namespace.semgrep.metadata[0].name
}

output "semgrep_cronjob_name" {
  description = "Name of the Semgrep CronJob (for `kubectl -n <ns> get cronjob` and ad-hoc debugging)."
  value       = kubernetes_cron_job_v1.semgrep.metadata[0].name
}

output "semgrep_irsa_role_arn" {
  description = "ARN of the IAM role assumed by the Semgrep service account via IRSA. Granted `s3:PutObject` / `s3:GetObject` / `s3:ListBucket` on `var.artifact_bucket`."
  value       = aws_iam_role.semgrep.arn
}

output "semgrep_env_secret_name" {
  description = "Name of the kubernetes secret holding Semgrep CronJob env vars (ARTIFACT_BUCKET, SEMGREP_REPO_LIST, AWS_REGION, GH_PAT). Useful for `kubectl -n <ns> get secret <name>` debugging."
  value       = kubernetes_secret.semgrep_env.metadata[0].name
}
