# ---------------------------------------------------------------------------
# Provider configuration. The Dependency-Track runtime references — but does
# not create — source-side resources. The Dependency-Track instance itself
# is user-provisioned (community-edition docker container on a dev VPC,
# or an existing user-run tenant). This module only resolves Databricks
# references the connector job consumes at run time:
#
#   - the bronze_dependency_track Unity Catalog schema (created by the
#     UC-bootstrap pipeline, referenced here so terraform plan fails fast
#     if the catalog / schema is absent);
#   - the secret-scope key holding the Dependency-Track API key.
# ---------------------------------------------------------------------------

# Bronze schema reference. The schema is created by the platform-wide UC
# bootstrap (sql/ddl/), not by this module — `data` proves it exists at
# plan time and surfaces its full name as an output for cross-tool wiring.
data "databricks_schema" "bronze_dependency_track" {
  name = "${var.catalog}.bronze_dependency_track"
}

# API-key secret reference. The secret is populated by scripts/load-secrets.sh
# (run by the user with $DT_APIKEY in the environment); `data` proves
# the scope+key pair exists at plan time so the connector job will not
# fail at ingestion start.
data "databricks_secret" "dependency_track_apikey" {
  scope = var.dependency_track_apikey_secret_scope
  key   = var.dependency_track_apikey_secret_key
}
