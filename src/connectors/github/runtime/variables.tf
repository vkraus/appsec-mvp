# ---------------------------------------------------------------------------
# AWS-side inputs (operator-supplied; what aws-foundation used to produce
# internally before the redesign).
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for ECR + IAM."
  type        = string
}

variable "aws_access_key_id" {
  description = "AWS access key ID (operator-supplied)."
  type        = string
  sensitive   = true
}

variable "aws_secret_access_key" {
  description = "AWS secret access key (operator-supplied)."
  type        = string
  sensitive   = true
}

variable "project_prefix" {
  description = "Short slug used to namespace AWS resources (ECR repo name, IAM role name)."
  type        = string
  default     = "appsec-mvp"
}

variable "eks_cluster_name" {
  description = "Operator-supplied EKS cluster name. The Juice Shop namespace and LoadBalancer Service are created in this cluster, and the GitHub Actions IAM role is granted cluster-admin via an EKS access entry. The operator must provide a working kubeconfig context that the kubernetes provider can consume."
  type        = string
}

# ---------------------------------------------------------------------------
# GitHub-side inputs.
# ---------------------------------------------------------------------------

variable "github_org" {
  description = "GitHub organization where seed repos are created."
  type        = string
}

variable "github_pat" {
  description = "GitHub PAT with org + repo admin permissions."
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Demo-data names (override only on collisions with operator's org).
# ---------------------------------------------------------------------------

variable "juiceshop_namespace" {
  description = "Kubernetes namespace for the Juice Shop deployment (target for ZAP scans)."
  type        = string
  default     = "juiceshop"
}

# ---------------------------------------------------------------------------
# Optional cross-scanner CI inputs. Leave empty if not using
# examples/end-to-end-demo/. Each Actions variable / secret is created on the
# Juice Shop seed repo only when the corresponding value is non-empty.
# ---------------------------------------------------------------------------

variable "sonarqube_url" {
  description = "(Optional) Public SonarQube URL consumed by the cross-scanner CI workflow."
  type        = string
  default     = ""
}

variable "sonarqube_project_token" {
  description = "(Optional) SonarQube project analysis token consumed by the cross-scanner CI workflow."
  type        = string
  sensitive   = true
  default     = ""
}

variable "zap_url" {
  description = "(Optional) Public ZAP URL consumed by the cross-scanner CI workflow."
  type        = string
  default     = ""
}

variable "artifact_bucket" {
  description = "(Optional) S3 artifact bucket name consumed by the cross-scanner CI workflow."
  type        = string
  default     = ""
}
