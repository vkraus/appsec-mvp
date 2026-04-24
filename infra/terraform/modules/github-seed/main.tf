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

resource "github_actions_variable" "juiceshop_vars" {
  for_each = {
    AWS_OIDC_ROLE_ARN      = var.aws_oidc_role_arn
    AWS_REGION             = var.aws_region
    ECR_REGISTRY_URI       = var.ecr_registry_uri
    ARTIFACT_BUCKET        = var.artifact_bucket
    SONARQUBE_URL          = var.sonarqube_url
    EKS_CLUSTER_NAME       = var.eks_cluster_name
    JUICESHOP_NAMESPACE    = var.juiceshop_namespace
    JUICESHOP_INGRESS_HOST = var.juiceshop_ingress_host
  }
  repository    = github_repository.juiceshop.name
  variable_name = each.key
  value         = each.value
}

resource "github_actions_secret" "juiceshop_sonar_token" {
  repository      = github_repository.juiceshop.name
  secret_name     = "SONARQUBE_TOKEN"
  plaintext_value = var.sonarqube_project_token
}
