#!/usr/bin/env bash
# install.sh — end-to-end installer for the github connector.
#
# Wraps the three steps a fresh operator runs to take an empty Databricks
# workspace + an existing GitHub org from zero to populated bronze + silver
# rows in `appsec_dev.bronze_github.*` and
# `appsec_dev.silver.{repositories,findings}`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret scope,
#     and the `silver` schema exist; `databricks bundle deploy --target dev`
#     has been run from repo root at least once so the `bronze_github` schema
#     and the `github-connector` job are registered).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or a
#     configured `~/.databrickscfg` profile).
#
# Required env vars
#   GITHUB_PAT  — fine-grained PAT or classic PAT (see load-secrets.sh).
#   GITHUB_ORG  — GitHub organization login.
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If unset,
#                       the verify step is skipped with a notice (the job still
#                       runs and rows still land — the user can verify by hand
#                       in the Databricks UI).
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".

set -euo pipefail

: "${GITHUB_PAT:?GITHUB_PAT is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading github secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the github-connector job (target=${TARGET})..."
databricks bundle run github-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_github.repositories;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.repositories WHERE source='github';"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.findings WHERE tool_source='github';"
else
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repositories FROM ${CATALOG}.bronze_github.repositories"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repos FROM ${CATALOG}.silver.repositories WHERE source='github'"
  databricks sql query --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='github'"
fi

echo "OK: github connector install complete."
