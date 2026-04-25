# ---------------------------------------------------------------------------
# Operator-supplied inputs for the Dependency-Track connector runtime.
#
# The Dependency-Track instance itself (community edition v4.10+ via docker
# on the operator's dev VPC, or an existing operator-run tenant) is
# operator-provisioned. This module references — but does not create — the
# Bronze schema and the Databricks secret holding the Dependency-Track API
# key.
# ---------------------------------------------------------------------------

variable "catalog" {
  description = "Unity Catalog catalog name (e.g. appsec_dev)."
  type        = string
}

variable "dependency_track_host" {
  description = "Dependency-Track instance host, FQDN no protocol, e.g. dt.example.com"
  type        = string
}

variable "dependency_track_apikey_secret_scope" {
  description = "Databricks secret scope holding the Dependency-Track API key."
  type        = string
  default     = "mvp-connectors"
}

variable "dependency_track_apikey_secret_key" {
  description = "Secret-key under the scope holding the Dependency-Track API key. Default matches config.yml's token_secret."
  type        = string
  default     = "dependency_track_api_key"
}
