#!/usr/bin/env bash
# install.sh — end-to-end installer for the semgrep connector.
#
# Step 1: load credentials into the mvp-connectors secret scope via load-secrets.sh.
# Step 2: trigger the semgrep-connector job in the configured target.
# Step 3: print (or run, if WAREHOUSE_ID is set) Bronze + Silver verification queries.

set -euo pipefail

: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${SEMGREP_PREFIX:?SEMGREP_PREFIX is required}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading semgrep secrets..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the semgrep-connector job (target=${TARGET})..."
databricks bundle run semgrep-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_semgrep.findings;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='semgrep';"
else
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.bronze_semgrep.findings"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='semgrep'"
fi

echo "OK: semgrep connector install complete."
