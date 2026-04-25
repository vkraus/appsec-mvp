# ---------------------------------------------------------------------------
# Operator-supplied inputs for the SonarQube connector runtime.
#
# The SonarQube server itself (SonarCloud SaaS or self-hosted SonarQube CE) is
# operator-provisioned. This module references — but does not create — the
# Bronze schema and the Databricks secret holding the SonarQube user token.
# ---------------------------------------------------------------------------

variable "catalog" {
  description = "Unity Catalog catalog name (e.g. appsec_dev)."
  type        = string
}

variable "sonarqube_host" {
  description = "SonarCloud or self-hosted SonarQube host (FQDN, no protocol)."
  type        = string
  default     = "sonarcloud.io"
}

variable "sonarqube_organization" {
  description = "SonarCloud organization key (or 'default' for self-hosted)."
  type        = string
}

variable "sonarqube_token_secret_scope" {
  description = "Databricks secret scope holding the SonarQube user token."
  type        = string
  default     = "mvp-connectors"
}

variable "sonarqube_token_secret_key" {
  description = "Secret-key under the scope holding the SonarQube token."
  type        = string
  default     = "sonarqube_token"
}
