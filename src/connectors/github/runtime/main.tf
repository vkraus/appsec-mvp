# ---------------------------------------------------------------------------
# Provider configuration. Operator credentials are passed in as variables; the
# kubernetes provider relies on the operator's local kubeconfig context (the
# original aws-foundation/scanners-eks split derived this from EKS data
# sources, which we replicate here so the github runtime is self-contained).
# ---------------------------------------------------------------------------

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key
}

provider "github" {
  owner = var.github_org
  token = var.github_pat
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
# ECR repository for Juice Shop image pushes from CI.
# (Migrated from infra/terraform/modules/aws-foundation/main.tf.)
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "juiceshop" {
  name                 = "${var.project_prefix}/juiceshop"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration { scan_on_push = true }
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC trust + IAM role used by the cross-scanner CI workflow
# to push to ECR and deploy to EKS without long-lived AWS keys.
# (Migrated from infra/terraform/modules/aws-foundation/main.tf.)
# ---------------------------------------------------------------------------

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/*:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_prefix}-gh-actions"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

resource "aws_iam_role_policy" "github_actions" {
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect   = "Allow"
          Action   = ["ecr:GetAuthorizationToken"]
          Resource = "*"
        },
        {
          Effect = "Allow"
          Action = [
            "ecr:BatchCheckLayerAvailability",
            "ecr:CompleteLayerUpload",
            "ecr:InitiateLayerUpload",
            "ecr:PutImage",
            "ecr:UploadLayerPart",
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer"
          ]
          Resource = aws_ecr_repository.juiceshop.arn
        },
        {
          Effect   = "Allow"
          Action   = ["eks:DescribeCluster"]
          Resource = data.aws_eks_cluster.this.arn
        }
      ],
      var.artifact_bucket == "" ? [] : [
        {
          Effect = "Allow"
          Action = [
            "s3:PutObject",
            "s3:GetObject",
            "s3:ListBucket"
          ]
          Resource = [
            "arn:aws:s3:::${var.artifact_bucket}",
            "arn:aws:s3:::${var.artifact_bucket}/cicd/*"
          ]
        }
      ]
    )
  })
}

# Grant the GH Actions role cluster-admin via EKS access entries so CI can
# kubectl-apply the Juice Shop deployment.
resource "aws_eks_access_entry" "github_actions" {
  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.github_actions.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "github_actions" {
  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.github_actions.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
}

# ---------------------------------------------------------------------------
# Juice Shop Kubernetes namespace + LoadBalancer Service (target for ZAP scans).
# The Juice Shop Deployment itself is applied by the GitHub Actions pipeline;
# Terraform only reserves the Service so the load-balancer hostname is stable
# across deploys.
# (Migrated from infra/terraform/modules/scanners-eks/main.tf.)
# ---------------------------------------------------------------------------

resource "kubernetes_namespace" "juiceshop" {
  metadata { name = var.juiceshop_namespace }
}

resource "kubernetes_service" "juiceshop" {
  metadata {
    name      = "juiceshop"
    namespace = kubernetes_namespace.juiceshop.metadata[0].name
  }
  spec {
    type     = "LoadBalancer"
    selector = { app = "juiceshop" }
    port {
      port        = 80
      target_port = 3000
    }
  }
}

data "kubernetes_service" "juiceshop" {
  metadata {
    name      = kubernetes_service.juiceshop.metadata[0].name
    namespace = kubernetes_namespace.juiceshop.metadata[0].name
  }
  depends_on = [kubernetes_service.juiceshop]
}

# ---------------------------------------------------------------------------
# Seed repositories (deliberately-vulnerable code for SAST/SCA targets).
# (Migrated from infra/terraform/modules/github-seed/main.tf.)
# ---------------------------------------------------------------------------

locals {
  seed_repos = {
    "seed-python-a"     = "seed-repo-a"
    "seed-javascript-b" = "seed-repo-b"
  }
}

resource "github_repository" "seed" {
  for_each = local.seed_repos

  name        = each.key
  description = "MVP seed repo — deliberately vulnerable fixture"
  visibility  = "private"
  auto_init   = true
}

resource "github_branch_default" "seed" {
  for_each   = github_repository.seed
  repository = each.value.name
  branch     = "main"
}

resource "github_branch_protection" "seed" {
  for_each      = github_repository.seed
  repository_id = each.value.node_id
  pattern       = "main"
  required_pull_request_reviews {
    required_approving_review_count = 0
  }
}

resource "github_repository_file" "seed_code" {
  for_each = merge([
    for repo_key, dir in local.seed_repos : {
      for file in fileset("${path.module}/files/${dir}", "**") :
      "${repo_key}/${file}" => {
        repository = repo_key
        file       = file
        content    = file("${path.module}/files/${dir}/${file}")
      }
    }
  ]...)

  repository          = each.value.repository
  file                = each.value.file
  content             = each.value.content
  commit_message      = "seed: vulnerable fixture"
  overwrite_on_create = true
  depends_on          = [github_repository.seed]
}

# ---------------------------------------------------------------------------
# Juice Shop fork (DAST target). The cross-scanner CI workflow itself
# (scan.yml) is intentionally NOT committed here — it lives at
# examples/end-to-end-demo/.github/workflows/scan.yml and is copied manually
# by the operator after this module runs.
# ---------------------------------------------------------------------------

resource "github_repository" "juiceshop" {
  name        = "juiceshop"
  description = "OWASP Juice Shop — CI/CD-step pattern demonstrator"
  visibility  = "private"
  auto_init   = true
}

resource "github_branch_default" "juiceshop" {
  repository = github_repository.juiceshop.name
  branch     = "main"
}

resource "github_repository_file" "juiceshop_files" {
  for_each = {
    for f in fileset("${path.module}/files/juiceshop", "**") : f => f
  }
  repository          = github_repository.juiceshop.name
  file                = each.value
  content             = file("${path.module}/files/juiceshop/${each.value}")
  commit_message      = "seed: juiceshop ${each.value}"
  overwrite_on_create = true
}

# ---------------------------------------------------------------------------
# GitHub Actions variables / secrets consumed by the cross-scanner CI workflow.
# Values that depend on other connectors' runtimes (sonarqube_url, zap_url,
# sonarqube_project_token, artifact_bucket) are operator-supplied optional
# inputs. Each variable / secret is created only when its value is non-empty,
# so this module remains usable when the operator is not running the full
# end-to-end demo.
# ---------------------------------------------------------------------------

locals {
  juiceshop_optional_vars = {
    AWS_OIDC_ROLE_ARN      = aws_iam_role.github_actions.arn
    AWS_REGION             = var.aws_region
    ECR_REGISTRY_URI       = aws_ecr_repository.juiceshop.repository_url
    EKS_CLUSTER_NAME       = var.eks_cluster_name
    JUICESHOP_NAMESPACE    = kubernetes_namespace.juiceshop.metadata[0].name
    JUICESHOP_INGRESS_HOST = try(data.kubernetes_service.juiceshop.status[0].load_balancer[0].ingress[0].hostname, "pending")
    SONARQUBE_URL          = var.sonarqube_url
    ZAP_URL                = var.zap_url
    ARTIFACT_BUCKET        = var.artifact_bucket
  }
  juiceshop_vars_to_create = {
    for k, v in local.juiceshop_optional_vars : k => v if v != ""
  }
}

resource "github_actions_variable" "juiceshop_vars" {
  for_each      = local.juiceshop_vars_to_create
  repository    = github_repository.juiceshop.name
  variable_name = each.key
  value         = each.value
}

resource "github_actions_secret" "juiceshop_sonar_token" {
  count           = var.sonarqube_project_token == "" ? 0 : 1
  repository      = github_repository.juiceshop.name
  secret_name     = "SONARQUBE_TOKEN"
  plaintext_value = var.sonarqube_project_token
}
