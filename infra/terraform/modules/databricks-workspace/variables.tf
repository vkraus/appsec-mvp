variable "workspace_url" {
  type = string
}

variable "metastore_id" {
  type = string
}

variable "artifact_bucket" {
  type = string
}

variable "artifact_bucket_role_arn" {
  type = string
}

variable "sonarqube_url" {
  type = string
}

variable "zap_url" {
  type = string
}

variable "github_org" {
  type = string
}

variable "github_pat" {
  type      = string
  sensitive = true
}

variable "servicenow_instance_url" {
  type = string
}

variable "servicenow_username" {
  type = string
}

variable "servicenow_password" {
  type      = string
  sensitive = true
}

variable "catalog_name" {
  description = "Unity Catalog name for this environment (appsec_dev, appsec_staging, appsec_prod)"
  type        = string
  # no default, callers must pass the env-specific value
}
