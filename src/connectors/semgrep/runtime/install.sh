#!/usr/bin/env bash
# Source-side install for the semgrep sast runtime.
#
# Sub-shape: terraform-aws-eks-cronjob
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/semgrep/runtime/.
#
# This runtime deploys a Semgrep CronJob on EKS that periodically clones a
# list of git repos, runs the bundled scan script, and writes JSON findings
# to an S3 artifact bucket via IRSA.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                       - must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID                - sensitive
#   AWS_SECRET_ACCESS_KEY            - sensitive
#   EKS_CLUSTER_NAME                 - EKS cluster where the CronJob runs
#   EKS_CLUSTER_OIDC_PROVIDER_ARN    - for the IRSA trust policy
#   ARTIFACT_BUCKET                  - S3 bucket name for JSON output
#   GITHUB_PAT_FOR_CLONE             - PAT for cloning target repos (sensitive)
#
# Optional:
#   REPO_URLS                  - comma-separated org/repo slugs (default: ["owasp/juice-shop"])
#   CRON_SCHEDULE              - default: 0 */6 * * *
#
# Idempotent: re-runs reconcile state with the AWS / EKS side.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"
: "${EKS_CLUSTER_OIDC_PROVIDER_ARN:?EKS_CLUSTER_OIDC_PROVIDER_ARN is required}"
: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${GITHUB_PAT_FOR_CLONE:?GITHUB_PAT_FOR_CLONE is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
export TF_VAR_eks_cluster_oidc_provider_arn="${EKS_CLUSTER_OIDC_PROVIDER_ARN}"
export TF_VAR_artifact_bucket="${ARTIFACT_BUCKET}"
export TF_VAR_github_pat_for_clone="${GITHUB_PAT_FOR_CLONE}"
[[ -n "${REPO_URLS:-}" ]] && export TF_VAR_repo_urls="[\"${REPO_URLS//,/\",\"}\"]"
[[ -n "${CRON_SCHEDULE:-}" ]] && export TF_VAR_cron_schedule="${CRON_SCHEDULE}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: semgrep source-side runtime apply complete."
echo "Outputs:"
terraform output
