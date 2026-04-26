#!/usr/bin/env bash
# install.sh — Databricks-side installer for the owasp_zap connector.
#
# Wraps the three steps a fresh operator runs to take an empty Databricks
# workspace from zero to populated bronze + silver rows in
# `appsec_dev.bronze_owasp_zap.findings` and
# `appsec_dev.silver.findings WHERE tool_source='owasp_zap'`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, mvp-connectors secret
#     scope, and the silver schema exist; `databricks bundle deploy
#     --target dev` has been run from repo root at least once so the
#     `bronze_owasp_zap` schema, the `zap_artifacts` UC Volume, and
#     the `owasp-zap-connector` job are registered).
#   - Databricks CLI authenticated.
#   - For the daemon path: a reachable ZAP daemon (typically provisioned
#     via `src/connectors/owasp_zap/runtime/`) and its API key.
#   - For the CI/CD-step artefact path: a CI/CD pipeline writing
#     zap-baseline.py / zap-full-scan.py JSON reports to
#     s3://${var.artifact_bucket}/zap/cicd/zap/<run>/ (the UC Volume
#     storage location).
#
# Required env vars (daemon path; the CI/CD-step path needs no extra
# env vars beyond the workspace's storage credential):
#   ZAP_URL
#   ZAP_API_KEY
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query.
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".

set -euo pipefail

: "${ZAP_URL:?ZAP_URL is required}"
: "${ZAP_API_KEY:?ZAP_API_KEY is required}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading owasp_zap secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the owasp-zap-connector job (target=${TARGET})..."
databricks bundle run owasp-zap-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_owasp_zap.findings;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='owasp_zap' AND category='dast';"
else
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.bronze_owasp_zap.findings"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='owasp_zap' AND category='dast'"
fi

echo "OK: owasp_zap connector install complete."
