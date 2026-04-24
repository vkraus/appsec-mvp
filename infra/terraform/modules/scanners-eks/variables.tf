variable "eks_cluster_name" {
  type = string
}

variable "sonarqube_db_endpoint" {
  type = string
}

variable "sonarqube_db_name" {
  type = string
}

variable "sonarqube_db_username" {
  type = string
}

variable "sonarqube_db_password" {
  type      = string
  sensitive = true
}

variable "sonarqube_admin_password" {
  type      = string
  sensitive = true
}

variable "artifact_bucket" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "semgrep_irsa_role_arn" { type = string }

variable "semgrep_repo_list" {
  type    = list(string)
  default = []
}

variable "github_pat_for_clone" {
  type      = string
  sensitive = true
  default   = ""
}
