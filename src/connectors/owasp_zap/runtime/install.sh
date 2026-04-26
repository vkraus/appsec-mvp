#!/usr/bin/env bash
# Source-side install for the owasp_zap dast runtime.
#
# Sub-shape: terraform-aws-eks-daemon
#
# This runtime deploys an OWASP ZAP daemon container on EKS via a Deployment +
# LoadBalancer Service, with a random API key stored in a Kubernetes Secret.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION              — must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID       — sensitive
#   AWS_SECRET_ACCESS_KEY   — sensitive
#   EKS_CLUSTER_NAME        — EKS cluster where the daemon runs
#
# Optional:
#   NAMESPACE_NAME          — default: zap
#   ZAP_IMAGE               — default: owasp/zap2docker-stable:2.14.0
#   SERVICE_PORT            — default: 8080
#
# Idempotent: re-runs reconcile state with the AWS / EKS side.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
[[ -n "${NAMESPACE_NAME:-}" ]] && export TF_VAR_namespace_name="${NAMESPACE_NAME}"
[[ -n "${ZAP_IMAGE:-}" ]] && export TF_VAR_zap_image="${ZAP_IMAGE}"
[[ -n "${SERVICE_PORT:-}" ]] && export TF_VAR_service_port="${SERVICE_PORT}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: owasp_zap source-side runtime apply complete."
echo "Outputs:"
terraform output
echo
echo "Note: on first apply the LoadBalancer hostname may still be unresolved"
echo "      (zap_url shows 'http://pending:...'). Re-run 'terraform apply'"
echo "      once AWS finishes provisioning the ELB to populate the hostname."
