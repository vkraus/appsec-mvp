#!/usr/bin/env bash
# install.sh — end-to-end installer for the GitHub connector.
#
# Wraps the three steps a fresh user runs to take an empty Databricks
# workspace + an existing GitHub org from zero to populated bronze rows in
# `appsec_dev.bronze_github.*` and silver rows in
# `appsec_dev.silver.{repositories,findings}`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret
#     scope, and the `silver` schema exist; `databricks bundle deploy
#     --target dev` has been run from repo root at least once so the
#     `bronze_github` schema and the `github-connector` job are registered).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or
#     a configured `~/.databrickscfg` profile).
#
# Required env vars
#   GITHUB_ORG  — GitHub organization slug the connector ingests
#   GITHUB_PAT  — fine-grained or classic PAT with `repo` + `read:org`
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If
#                       unset, the verify step is skipped with a notice.
#   CATALOG           — Unity Catalog name. Defaults to "appsec_dev".
#
# Idempotent: re-runs overwrite secret values and re-trigger the job.

set -euo pipefail

: "${GITHUB_ORG:?GITHUB_ORG is required (organization slug)}"
: "${GITHUB_PAT:?GITHUB_PAT is required (PAT with repo + read:org)}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading GitHub secrets into the mvp-connectors scope..."
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
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repos_bronze FROM ${CATALOG}.bronze_github.repositories"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repos FROM ${CATALOG}.silver.repositories WHERE source='github'"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='github'"
fi

echo "OK: github connector install complete."
