#!/usr/bin/env bash
# install.sh — end-to-end installer for the GitLab connector.
#
# Wraps the three steps a fresh operator runs to take an empty Databricks
# workspace + an existing GitLab group from zero to populated bronze + silver
# rows in `appsec_dev.bronze_gitlab.*` and `appsec_dev.silver.{repositories,findings}`.
#
# Prerequisites
#   - Phase 1 platform install complete (catalog, `mvp-connectors` secret scope,
#     and the `silver` schema exist; `databricks bundle deploy --target dev`
#     has been run from repo root at least once so the `bronze_gitlab` schema
#     and the `gitlab-connector` job are registered).
#   - Databricks CLI authenticated (DATABRICKS_HOST + DATABRICKS_TOKEN, or a
#     configured `~/.databrickscfg` profile).
#
# Required env vars
#   GITLAB_BASE_URL   — e.g. "https://gitlab.com" or self-hosted FQDN.
#   GITLAB_GROUP_ID   — numeric GitLab group ID (Settings → General → Group ID).
#   GITLAB_TOKEN      — PAT or group access token with read_api +
#                       read_repository + read_user scopes.
#
# Optional env vars
#   DATABRICKS_TARGET — bundle target to run against. Defaults to "dev".
#   WAREHOUSE_ID      — SQL warehouse ID for the verification query. If unset,
#                       the verify step is skipped with a notice (the job still
#                       runs and rows still land — the user can verify by hand
#                       in the Databricks UI).
#   CATALOG           — Unity Catalog name for the verify query. Defaults to
#                       "appsec_dev".
#
# Idempotent: re-runs overwrite secret values and re-trigger the job.

set -euo pipefail

: "${GITLAB_BASE_URL:?GITLAB_BASE_URL is required (e.g. https://gitlab.com)}"
: "${GITLAB_GROUP_ID:?GITLAB_GROUP_ID is required (numeric, from GitLab UI)}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is required (PAT with read_api + read_repository + read_user)}"

TARGET="${DATABRICKS_TARGET:-dev}"
CATALOG="${CATALOG:-appsec_dev}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "Step 1/3: Loading GitLab secrets into the mvp-connectors scope..."
bash "${SCRIPT_DIR}/load-secrets.sh"

echo "Step 2/3: Triggering the gitlab-connector job (target=${TARGET})..."
databricks bundle run gitlab-connector --target "${TARGET}"

echo "Step 3/3: Verifying row counts..."
if [[ -z "${WAREHOUSE_ID:-}" ]]; then
  echo "  WAREHOUSE_ID not set — skipping SQL verification."
  echo "  To verify by hand, run in a Databricks SQL editor:"
  echo "    SELECT count(*) FROM ${CATALOG}.bronze_gitlab.projects;"
  echo "    SELECT count(*) FROM ${CATALOG}.silver.repositories WHERE source='gitlab';"
else
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_projects FROM ${CATALOG}.bronze_gitlab.projects"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_repos FROM ${CATALOG}.silver.repositories WHERE source='gitlab'"
  databricks sql query \
    --warehouse-id "${WAREHOUSE_ID}" \
    "SELECT count(*) AS n_findings FROM ${CATALOG}.silver.findings WHERE tool_source='gitlab'"
fi

echo "OK: gitlab connector install complete."
