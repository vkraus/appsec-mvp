#!/usr/bin/env bash
# install.sh — end-to-end installer for the OWASP ZAP connector.
#
# Wraps the three steps a fresh user runs to take an empty Databricks
# workspace + a reachable ZAP daemon from zero to populated bronze rows in
# `appsec_dev.bronze_owasp_zap.findings` and silver rows in
# `appsec_dev.silver.findings`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret
#     scope, and the `silver` schema exist; `databricks bundle deploy
#     --target dev` has been run from repo root at least once so the
#     `bronze_owasp_zap` schema and the `owasp-zap-connector` job are
#     registered).
#   - A ZAP daemon is running and reachable from the workspace (either the
#     optional source runtime in `src/connectors/owasp_zap/runtime/` or a
#     user-managed instance). At least one scan has produced alerts.
#   - Databricks CLI authenticated.
#
# Required env vars
#   ZAP_URL      — public URL of the ZAP daemon, e.g. http://lb-host:8080
#                  (matches the `zap_url` output of the optional runtime).
#   ZAP_API_KEY  — 40-char API key configured on the daemon
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If
#                       unset, the verify step is skipped with a notice.
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".
#
# Idempotent: re-runs overwrite secret values and re-trigger the job.

set -euo pipefail

: "${ZAP_URL:?ZAP_URL is required (e.g. http://lb-host:8080)}"
: "${ZAP_API_KEY:?ZAP_API_KEY is required (40-char daemon API key)}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading OWASP ZAP secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the owasp-zap-connector job (target=${TARGET})..."
databricks bundle run owasp-zap-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_owasp_zap.findings;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='owasp_zap';"
else
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.bronze_owasp_zap.findings"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='owasp_zap'"
fi

echo "OK: owasp_zap connector install complete."
