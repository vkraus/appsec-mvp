# ---------------------------------------------------------------------------
# User-supplied inputs for the TruffleHog source-system runtime.
#
# TruffleHog is a CLI-artefact connector: scans run on CI/CD runners and
# write `--json` line-delimited output to a cloud bucket (S3 / ADLS / GCS).
# This runtime declares the Unity Catalog Volume that maps onto that bucket
# so autoloader-style ingestion can read the artefacts.
# ---------------------------------------------------------------------------

variable "catalog" {
  description = "Unity Catalog name. The TruffleHog UC Volume is created in `<catalog>.bronze_trufflehog.artefacts`. Must match the catalog the connector's bundle targets."
  type        = string
}

variable "trufflehog_artifact_volume_path" {
  description = "UC Volume path for ingesting TruffleHog JSON artefacts, e.g. /Volumes/appsec_dev/bronze_trufflehog/artefacts. The underlying cloud bucket (S3 / ADLS / GCS) must be pre-provisioned by the user; this runtime only creates the UC Volume that maps to it."
  type        = string
}

variable "trufflehog_artifact_volume_secret_scope" {
  description = "Databricks secret scope holding the AWS (or equivalent) credentials with read access to the artefact bucket. Loaded by `scripts/load-secrets.sh`."
  type        = string
  default     = "mvp-connectors"
}

variable "trufflehog_artifact_volume_secret_key" {
  description = "Databricks secret key under `var.trufflehog_artifact_volume_secret_scope` holding a JSON blob `{access_key_id, secret_access_key}` for the artefact bucket reader."
  type        = string
  default     = "trufflehog_aws_credentials"
}
