#!/usr/bin/env bash
# Source-side install for the servicenow cmdb runtime.
#
# Provisions seed CMDB records in the servicenow tenant via the REST
# table API. Wraps `terraform init` + `terraform apply` against
# src/connectors/servicenow/runtime/.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   SERVICENOW_INSTANCE_URL   — tenant URL, e.g. https://devXXXXX.service-now.com
#   SERVICENOW_ADMIN_USERNAME — service-account user with write access to
#                               cmdb_ci_business_app, cmdb_ci_appl, cmdb_rel_ci
#   SERVICENOW_ADMIN_PASSWORD — service-account password (sensitive)
#
# Optional environment variables:
#   SEED_REPO_NAMES   — comma-separated list (default: BenchmarkJava,BenchmarkPython,juice-shop)
#   PROJECT_PREFIX    — short slug (default: appsec-mvp)
#
# Apply prerequisites: bash, curl, jq must all be on PATH at apply time.
# On Windows hosts, run from WSL or Git Bash.
#
# Idempotent: re-runs skip records whose triggers_replace keys are unchanged.
# Drift caused by manual edits in the servicenow UI is NOT detected — taint
# the relevant terraform_data resources before re-applying if needed.

set -euo pipefail

: "${SERVICENOW_INSTANCE_URL:?SERVICENOW_INSTANCE_URL is required}"
: "${SERVICENOW_ADMIN_USERNAME:?SERVICENOW_ADMIN_USERNAME is required}"
: "${SERVICENOW_ADMIN_PASSWORD:?SERVICENOW_ADMIN_PASSWORD is required}"

for cmd in bash curl jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not on PATH" >&2; exit 1; }
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

export TF_VAR_instance_url="${SERVICENOW_INSTANCE_URL}"
export TF_VAR_admin_username="${SERVICENOW_ADMIN_USERNAME}"
export TF_VAR_admin_password="${SERVICENOW_ADMIN_PASSWORD}"
[[ -n "${SEED_REPO_NAMES:-}" ]] && export TF_VAR_seed_repo_names="[\"${SEED_REPO_NAMES//,/\",\"}\"]"
[[ -n "${PROJECT_PREFIX:-}" ]] && export TF_VAR_project_prefix="${PROJECT_PREFIX}"

cd "${SCRIPT_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: servicenow CMDB seed apply complete."
echo "Outputs:"
terraform output
