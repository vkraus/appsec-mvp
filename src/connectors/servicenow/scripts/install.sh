#!/usr/bin/env bash
# install.sh — end-to-end installer for the ServiceNow connector.
#
# Wraps the three steps a fresh user runs to take an empty Databricks
# workspace + an existing ServiceNow tenant from zero to populated bronze
# rows in `appsec_dev.bronze_servicenow.business_applications` and silver
# CMDB rows in `appsec_dev.silver.business_applications`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret
#     scope, and the `silver` schema exist; `databricks bundle deploy
#     --target dev` has been run from the repo root at least once so the
#     `bronze_servicenow` schema and the `servicenow_ingest` pipeline are
#     registered).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or
#     a configured `~/.databrickscfg` profile).
#
# Required env vars
#   SERVICENOW_URL       — instance URL, e.g. https://devXXXXX.service-now.com
#   SERVICENOW_USERNAME  — service-account username
#   SERVICENOW_PASSWORD  — service-account password
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If
#                       unset, the verify step is skipped with a notice.
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".
#
# Idempotent: re-runs overwrite secret values and re-trigger the pipeline.

set -euo pipefail

: "${SERVICENOW_URL:?SERVICENOW_URL is required (e.g. https://devXXXXX.service-now.com)}"
: "${SERVICENOW_USERNAME:?SERVICENOW_USERNAME is required (service-account username)}"
: "${SERVICENOW_PASSWORD:?SERVICENOW_PASSWORD is required (service-account password)}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading ServiceNow secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the servicenow_ingest pipeline (target=${TARGET})..."
databricks bundle run servicenow_ingest --target "${TARGET}" --refresh-all

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_servicenow.business_applications;"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_servicenow.app_cis;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.business_applications;"
else
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_apps_bronze FROM ${CATALOG}.bronze_servicenow.business_applications"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_app_cis_bronze FROM ${CATALOG}.bronze_servicenow.app_cis"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_apps_silver FROM ${CATALOG}.silver.business_applications"
fi

echo "OK: servicenow connector install complete."
