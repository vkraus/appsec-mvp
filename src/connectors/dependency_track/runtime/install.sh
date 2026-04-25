#!/usr/bin/env bash
# Source-side install for the dependency_track sca runtime.
#
# Sub-shape: terraform-references-only.
# This runtime DOES NOT provision a dependency_track tenant. The
# dependency_track instance (community-edition v4.10+ via docker on a dev
# VPC, or an existing user-run tenant) is user-provisioned out of band.
#
# What this script does:
#   1. Verifies the Bronze schema (${CATALOG}.bronze_dependency_track) exists.
#   2. Verifies the API-key Databricks secret is reachable.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                   — Unity Catalog name (e.g. appsec_dev)
#   DEPENDENCY_TRACK_HOST     — instance host (FQDN, no protocol, e.g. dt.example.com)
#
# Optional:
#   DEPENDENCY_TRACK_APIKEY_SECRET_SCOPE — default: mvp-connectors
#   DEPENDENCY_TRACK_APIKEY_SECRET_KEY   — default: dependency_track_api_key
#
# Prerequisites:
#   - The catalog and `bronze_dependency_track` schema must exist
#     (`databricks bundle run uc-schema-bootstrap --target dev`).
#   - The API-key secret must be loaded (`bash ../scripts/load-secrets.sh`).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or
#     a configured `~/.databrickscfg` profile).
#
# Idempotent: re-runs simply re-resolve the data sources.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${DEPENDENCY_TRACK_HOST:?DEPENDENCY_TRACK_HOST is required (FQDN, no protocol)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_dependency_track_host="${DEPENDENCY_TRACK_HOST}"
[[ -n "${DEPENDENCY_TRACK_APIKEY_SECRET_SCOPE:-}" ]] && export TF_VAR_dependency_track_apikey_secret_scope="${DEPENDENCY_TRACK_APIKEY_SECRET_SCOPE}"
[[ -n "${DEPENDENCY_TRACK_APIKEY_SECRET_KEY:-}" ]] && export TF_VAR_dependency_track_apikey_secret_key="${DEPENDENCY_TRACK_APIKEY_SECRET_KEY}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: dependency_track source-side runtime apply complete (references-only)."
echo "Outputs:"
terraform output
