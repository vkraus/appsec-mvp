variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "aws_access_key_id" {
  type      = string
  sensitive = true
}

variable "aws_secret_access_key" {
  type      = string
  sensitive = true
}

variable "owner_tag" {
  type = string
}

variable "databricks_workspace_url" {
  type = string
}

variable "databricks_pat" {
  type      = string
  sensitive = true
}

variable "databricks_account_id" {
  type = string
}

variable "databricks_metastore_id" {
  type        = string
  description = "Unity Catalog metastore ID for the workspace's region."
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

variable "servicenow_admin_username" {
  type = string
}

variable "servicenow_admin_password" {
  type      = string
  sensitive = true
}

variable "sonarqube_admin_password" {
  type        = string
  sensitive   = true
  description = "Initial admin password for SonarQube. Must be rotated after first login."
}

variable "project_prefix" {
  type        = string
  default     = "appsec-mvp"
  description = "Used as the prefix for named AWS resources."
}

variable "catalog_name" {
  type        = string
  description = "Unity Catalog name for this environment (appsec_dev, appsec_staging, appsec_prod)."
  # no default, forces callers to pass the env-specific value
}
