# ---------------------------------------------------------------------------
# AWS-side inputs (user-supplied; what aws-foundation used to produce
# internally before the redesign).
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for EKS + the artifact S3 bucket. Must match the region of `eks_cluster_name`."
  type        = string
}

variable "aws_access_key_id" {
  description = "AWS access key ID (user-supplied)."
  type        = string
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "AWS secret access key (user-supplied)."
  type        = string
  sensitive   = true
}

variable "project_prefix" {
  description = "Short slug used to namespace AWS resources (IAM role name, IAM policy name, tags)."
  type        = string
  default     = "appsec-mvp"
}

# ---------------------------------------------------------------------------
# EKS target — where the Semgrep CronJob runs.
# ---------------------------------------------------------------------------

variable "eks_cluster_name" {
  description = "User-supplied EKS cluster name. The Semgrep namespace, service account, ConfigMap, Secret, and CronJob are created in this cluster. Must be in `var.aws_region` — the kubernetes provider's auth flow resolves the cluster endpoint via the AWS provider's region."
  type        = string
}

variable "eks_cluster_oidc_provider_arn" {
  description = "ARN of the IAM OIDC provider associated with the EKS cluster (output by your EKS module as `oidc_provider_arn`). Required to mint the IRSA trust policy that lets the `semgrep` service account assume this module's IAM role. Must reference the same cluster as `eks_cluster_name`."
  type        = string
}

# ---------------------------------------------------------------------------
# S3 artifact destination. The Semgrep CronJob writes JSON findings to
# s3://${artifact_bucket}/periodic/semgrep/<repo>/<timestamp>.json. The IRSA
# IAM role grants the service account write access to this bucket.
# ---------------------------------------------------------------------------

variable "artifact_bucket" {
  description = "S3 bucket name where the Semgrep CronJob writes its JSON findings. The IRSA role this module creates is granted `s3:PutObject` / `s3:GetObject` / `s3:ListBucket` on this bucket and its objects."
  type        = string
}

# ---------------------------------------------------------------------------
# Repo list to scan + the PAT used to clone them. The bundled
# `files/semgrep-scan.sh` reads `SEMGREP_REPO_LIST` (comma-separated `org/repo`
# slugs) and clones each via `https://x-access-token:${GH_PAT}@github.com/...`.
# Users with arbitrary git URLs / non-GitHub hosts must replace the script.
# ---------------------------------------------------------------------------

variable "repo_urls" {
  description = "Non-empty list of repositories the Semgrep CronJob clones and scans. The bundled `files/semgrep-scan.sh` expects `org/repo` slugs (e.g. `[\"owasp/juice-shop\"]`); the script joins them with commas into the `SEMGREP_REPO_LIST` env var, then clones each via `https://x-access-token:$${GH_PAT}@github.com/$${slug}.git`. Users with arbitrary git URLs or non-GitHub hosts must override the script."
  type        = list(string)
  default     = ["owasp/juice-shop"]
}

variable "github_pat_for_clone" {
  description = "GitHub PAT used by `semgrep-scan.sh` to clone the repos in `var.repo_urls`. Required even for public repos because the script always injects the token into the clone URL. Sensitive."
  type        = string
  sensitive   = true
  default     = ""
}

# ---------------------------------------------------------------------------
# Semgrep CronJob configuration.
# ---------------------------------------------------------------------------

variable "namespace_name" {
  description = "Kubernetes namespace for the Semgrep CronJob, ServiceAccount, ConfigMap, and Secret."
  type        = string
  default     = "semgrep"
}

variable "semgrep_image" {
  description = "Container image used by the Semgrep CronJob. Captured as a variable for reproducibility — the source module hard-coded `returntocorp/semgrep:latest`."
  type        = string
  default     = "returntocorp/semgrep:latest"
}

variable "cron_schedule" {
  description = "Cron schedule for the Semgrep CronJob. Default mirrors the source module (`0 */6 * * *` — every six hours)."
  type        = string
  default     = "0 */6 * * *"
}
