#!/usr/bin/env bash
# install.sh — end-to-end installer for the sonarqube connector.
#
# Step 1: load credentials into the mvp-connectors secret scope via load-secrets.sh.
# Step 2: trigger the sonarqube-connector job in the configured target.
# Step 3: print (or run, if WAREHOUSE_ID is set) Bronze + Silver verification queries.

set -euo pipefail

: "${SONARQUBE_URL:?SONARQUBE_URL is required}"
: "${SONARQUBE_TOKEN:?SONARQUBE_TOKEN is required}"
: "${SONARQUBE_HOST:?SONARQUBE_HOST is required}"
: "${SONARQUBE_ORG:?SONARQUBE_ORG is required}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading sonarqube secrets..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the sonarqube-connector job (target=${TARGET})..."
databricks bundle run sonarqube-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_sonarqube.issues;"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_sonarqube.findings_raw;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='sonarqube';"
else
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze_issues FROM ${CATALOG}.bronze_sonarqube.issues"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze_findings_raw FROM ${CATALOG}.bronze_sonarqube.findings_raw"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='sonarqube'"
fi

echo "OK: sonarqube connector install complete."
