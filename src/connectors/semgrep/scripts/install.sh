#!/usr/bin/env bash
# install.sh — end-to-end installer for the Semgrep connector.
#
# Wraps the three steps a fresh user runs to take an empty Databricks
# workspace + an existing S3 bucket of Semgrep `--json` artefacts from zero
# to populated bronze rows in `appsec_dev.bronze_semgrep.findings` and
# silver rows in `appsec_dev.silver.findings`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret
#     scope, and the `silver` schema exist; `databricks bundle deploy
#     --target dev` has been run from repo root at least once so the
#     `bronze_semgrep` schema and the `semgrep-connector` job are
#     registered).
#   - Semgrep CI/CD jobs are writing `--json` line-delimited findings to a
#     shared S3 bucket prefix (or UC Volume). At least one artefact present
#     before this script runs.
#   - Databricks CLI authenticated.
#
# Required env vars
#   ARTIFACT_BUCKET — S3 bucket name (no `s3://` prefix) holding Semgrep
#                     artefacts. Used by the autoloader-style ingest.
#
# Optional env vars
#   SEMGREP_PREFIX    — key prefix within the bucket. Default "semgrep/".
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If
#                       unset, the verify step is skipped with a notice.
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".
#
# Idempotent: re-runs overwrite secret values and re-trigger the job.

set -euo pipefail

: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required (S3 bucket holding Semgrep --json artefacts)}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading Semgrep secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the semgrep-connector job (target=${TARGET})..."
databricks bundle run semgrep-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_semgrep.findings;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='semgrep';"
else
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_bronze FROM ${CATALOG}.bronze_semgrep.findings"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='semgrep'"
fi

echo "OK: semgrep connector install complete."
