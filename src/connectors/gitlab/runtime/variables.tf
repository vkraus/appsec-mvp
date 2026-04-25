# ---------------------------------------------------------------------------
# Operator-supplied inputs for the GitLab connector runtime.
#
# The GitLab tenant itself (gitlab.com or self-hosted) is operator-provisioned.
# This module references — but does not create — the Bronze schema and the
# Databricks secret holding the GitLab Personal Access Token.
# ---------------------------------------------------------------------------

variable "catalog" {
  description = "Unity Catalog catalog name (e.g. appsec_dev)."
  type        = string
}

variable "gitlab_host" {
  description = "GitLab tenant host (gitlab.com or self-hosted FQDN)."
  type        = string
  default     = "gitlab.com"
}

variable "gitlab_group_id" {
  description = "GitLab group ID to ingest from."
  type        = string
}

variable "gitlab_token_secret_scope" {
  description = "Databricks secret scope holding the GitLab personal access token."
  type        = string
  default     = "mvp-connectors"
}

variable "gitlab_token_secret_key" {
  description = "Secret-key under the scope holding the GitLab token."
  type        = string
  default     = "gitlab_token"
}
