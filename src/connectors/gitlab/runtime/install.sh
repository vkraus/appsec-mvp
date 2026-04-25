#!/usr/bin/env bash
# Source-side install for the gitlab scm runtime.
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/gitlab/runtime/.
#
# Sub-shape: terraform-references-only
# This runtime is references-only — it pins providers, declares user inputs,
# and exports the Bronze schema name + gitlab host as outputs. It does NOT
# provision a gitlab tenant, group, or projects. The gitlab tenant is
# user-provisioned out of band.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG           — Unity Catalog name (e.g. appsec_dev)
#   GITLAB_GROUP_ID   — numeric gitlab group/org ID
#
# Optional:
#   GITLAB_HOST       — tenant host (default: gitlab.com)
#
# Idempotent: re-runs reconcile state with the gitlab side.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_dev)}"
: "${GITLAB_GROUP_ID:?GITLAB_GROUP_ID is required (numeric)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_gitlab_group_id="${GITLAB_GROUP_ID}"
[[ -n "${GITLAB_HOST:-}" ]] && export TF_VAR_gitlab_host="${GITLAB_HOST}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: gitlab source-side runtime apply complete."
echo "Outputs:"
terraform output
