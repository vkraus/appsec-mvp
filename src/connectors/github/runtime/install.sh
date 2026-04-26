#!/usr/bin/env bash
# Source-side install for the github scm runtime.
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/github/runtime/.
#
# Sub-shape: terraform-aws-github
#
# This runtime provisions:
#   - ECR repository for image pushes
#   - GitHub-Actions OIDC trust + IAM role
#   - EKS access entry granting cluster-admin to the GH-Actions role
#   - Juice Shop namespace + LoadBalancer Service (target for ZAP)
#   - GitHub repo overlays + Actions variables/secrets in the Juice Shop fork
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                — AWS region for ECR + IAM
#   AWS_ACCESS_KEY_ID         — AWS access key (sensitive)
#   AWS_SECRET_ACCESS_KEY     — AWS secret key (sensitive)
#   EKS_CLUSTER_NAME          — EKS cluster (must be in $AWS_REGION)
#   GITHUB_ORG                — GitHub org owning the seeded repos
#   GITHUB_PAT                — GitHub PAT with org+repo admin (sensitive)
#
# Optional cross-scanner CI inputs (left empty when not running end-to-end demo):
#   SONARQUBE_URL, SONARQUBE_PROJECT_TOKEN, ZAP_URL, ARTIFACT_BUCKET
#
# Idempotent: re-runs reconcile state with the GitHub side.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"
: "${GITHUB_PAT:?GITHUB_PAT is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
export TF_VAR_github_org="${GITHUB_ORG}"
export TF_VAR_github_pat="${GITHUB_PAT}"
[[ -n "${SONARQUBE_URL:-}" ]] && export TF_VAR_sonarqube_url="${SONARQUBE_URL}"
[[ -n "${SONARQUBE_PROJECT_TOKEN:-}" ]] && export TF_VAR_sonarqube_project_token="${SONARQUBE_PROJECT_TOKEN}"
[[ -n "${ZAP_URL:-}" ]] && export TF_VAR_zap_url="${ZAP_URL}"
[[ -n "${ARTIFACT_BUCKET:-}" ]] && export TF_VAR_artifact_bucket="${ARTIFACT_BUCKET}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: github source-side runtime apply complete."
echo "Outputs:"
terraform output
