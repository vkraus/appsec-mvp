# ---------------------------------------------------------------------------
# Provider configuration. Operator credentials are passed in as variables;
# Kubernetes auth is derived from EKS data sources (the original
# aws-foundation/scanners-eks split derived this from EKS data sources via
# module outputs, which we replicate here so the semgrep runtime is
# self-contained).
# ---------------------------------------------------------------------------

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key
}

data "aws_eks_cluster" "this" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = var.eks_cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this.token
}

# ---------------------------------------------------------------------------
# Input validation. Cross-variable contracts are easier to express as
# preconditions on a no-op `terraform_data` sentinel than as `validation`
# blocks (which can only see a single variable). These fire at plan time,
# turning otherwise opaque runtime errors (CronJob booting with no bucket to
# write to; CronJob looping with no repos to scan) into clear messages.
# ---------------------------------------------------------------------------

resource "terraform_data" "input_validation" {
  lifecycle {
    precondition {
      condition     = var.artifact_bucket != ""
      error_message = "var.artifact_bucket is required — the Semgrep CronJob has no destination for its JSON findings without it."
    }
    precondition {
      condition     = length(var.repo_urls) > 0
      error_message = "var.repo_urls must contain at least one repository — the Semgrep CronJob has nothing to scan otherwise."
    }
    precondition {
      condition     = var.eks_cluster_oidc_provider_arn != ""
      error_message = "var.eks_cluster_oidc_provider_arn is required — the IRSA trust policy for the Semgrep service account references it directly."
    }
    precondition {
      condition     = var.github_pat_for_clone != ""
      error_message = "var.github_pat_for_clone is required — files/semgrep-scan.sh enforces $${GH_PAT:?set GH_PAT} and clones every repo via the token URL, even public ones."
    }
  }
}

# ---------------------------------------------------------------------------
# IRSA IAM role for the Semgrep service account. Inlined from the original
# `module "semgrep_irsa"` (terraform-aws-modules/iam/aws//modules/
# iam-role-for-service-accounts-eks) plus the supporting
# `aws_iam_policy.artifact_bucket_write` — kept as raw resources so this
# runtime is free of community-module pinning.
# ---------------------------------------------------------------------------

# Derive the OIDC issuer URL (without scheme) from the provider ARN. The
# trust policy's `sub` condition keys off this issuer, matching the shape
# the community IRSA module produces.
locals {
  oidc_issuer = replace(var.eks_cluster_oidc_provider_arn, "/^arn:aws:iam::[0-9]+:oidc-provider\\//", "")
}

data "aws_iam_policy_document" "irsa_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_cluster_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:sub"
      values   = ["system:serviceaccount:${var.namespace_name}:semgrep"]
    }
  }
}

resource "aws_iam_role" "semgrep" {
  name               = "${var.project_prefix}-semgrep"
  assume_role_policy = data.aws_iam_policy_document.irsa_assume.json

  tags = { Name = "${var.project_prefix}-semgrep" }
}

# Mirrors the source module's `aws_iam_policy.artifact_bucket_write` —
# `s3:PutObject` / `s3:GetObject` / `s3:ListBucket` on the artifact bucket
# and its objects. Attached inline rather than as a separate
# `aws_iam_policy` + `aws_iam_role_policy_attachment` for brevity.
data "aws_iam_policy_document" "irsa_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::${var.artifact_bucket}",
      "arn:aws:s3:::${var.artifact_bucket}/*",
    ]
  }
}

resource "aws_iam_role_policy" "semgrep" {
  name   = "${var.project_prefix}-semgrep-artifact-bucket-write"
  role   = aws_iam_role.semgrep.id
  policy = data.aws_iam_policy_document.irsa_policy.json
}

# ---------------------------------------------------------------------------
# Semgrep Kubernetes namespace, service account, ConfigMap, Secret, CronJob.
# (Migrated from infra/terraform/modules/scanners-eks/main.tf — the Semgrep
# slice only; the SonarQube / ZAP / Juice Shop slices belong to other
# connectors' runtimes.)
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "semgrep" {
  metadata { name = var.namespace_name }
}

resource "kubernetes_service_account" "semgrep" {
  metadata {
    name      = "semgrep"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.semgrep.arn
    }
  }
}

resource "kubernetes_config_map" "semgrep_script" {
  metadata {
    name      = "semgrep-script"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  data = {
    "scan.sh" = file("${path.module}/files/semgrep-scan.sh")
  }
}

resource "kubernetes_secret" "semgrep_env" {
  metadata {
    name      = "semgrep-env"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  data = {
    ARTIFACT_BUCKET   = var.artifact_bucket
    SEMGREP_REPO_LIST = join(",", var.repo_urls)
    AWS_REGION        = var.aws_region
    GH_PAT            = var.github_pat_for_clone
  }
}

resource "kubernetes_cron_job_v1" "semgrep" {
  metadata {
    name      = "semgrep-periodic"
    namespace = kubernetes_namespace.semgrep.metadata[0].name
  }
  spec {
    schedule = var.cron_schedule
    job_template {
      metadata {}
      spec {
        template {
          metadata {}
          spec {
            service_account_name = kubernetes_service_account.semgrep.metadata[0].name
            restart_policy       = "OnFailure"

            container {
              name    = "semgrep"
              image   = var.semgrep_image
              command = ["/bin/bash", "/scripts/scan.sh"]

              env_from {
                secret_ref { name = kubernetes_secret.semgrep_env.metadata[0].name }
              }

              volume_mount {
                name       = "script"
                mount_path = "/scripts"
              }
            }

            volume {
              name = "script"
              config_map {
                name         = kubernetes_config_map.semgrep_script.metadata[0].name
                default_mode = "0755"
              }
            }
          }
        }
      }
    }
  }
}
