provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key_id
  secret_key = var.aws_secret_access_key
  default_tags {
    tags = {
      Project = "appsec-mvp"
      Owner   = var.owner_tag
    }
  }
}

provider "kubernetes" {
  host                   = module.aws_foundation.eks_cluster_endpoint
  cluster_ca_certificate = base64decode(module.aws_foundation.eks_cluster_ca)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.aws_foundation.eks_cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.aws_foundation.eks_cluster_endpoint
    cluster_ca_certificate = base64decode(module.aws_foundation.eks_cluster_ca)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.aws_foundation.eks_cluster_name, "--region", var.aws_region]
    }
  }
}

provider "databricks" {
  host  = var.databricks_workspace_url
  token = var.databricks_pat
}

provider "github" {
  owner = var.github_org
  token = var.github_pat
}
