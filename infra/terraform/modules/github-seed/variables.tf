variable "github_org" {
  type = string
}

variable "aws_oidc_role_arn" {
  type = string
}

variable "ecr_registry_uri" {
  type = string
}

variable "artifact_bucket" {
  type = string
}

variable "sonarqube_url" {
  type = string
}

variable "sonarqube_project_token" {
  type      = string
  sensitive = true
}

variable "zap_url" {
  type = string
}

variable "eks_cluster_name" {
  type = string
}

variable "juiceshop_namespace" {
  type = string
}

variable "juiceshop_ingress_host" {
  type = string
}

variable "aws_region" {
  type = string
}
