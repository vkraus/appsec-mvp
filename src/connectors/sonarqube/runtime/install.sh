#!/usr/bin/env bash
# Source-side install for the sonarqube sast runtime.
#
# Sub-shape: terraform-aws-eks-helm
#
# Wraps `terraform init` + `terraform apply` against
# src/connectors/sonarqube/runtime/.
#
# This runtime deploys SonarQube as a Helm release on EKS, optionally with a
# dedicated RDS Postgres backing store, exposed via a LoadBalancer Service.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   AWS_REGION                    - must match the region of $EKS_CLUSTER_NAME
#   AWS_ACCESS_KEY_ID             - sensitive
#   AWS_SECRET_ACCESS_KEY         - sensitive
#   EKS_CLUSTER_NAME              - EKS cluster where SonarQube is installed
#   SONARQUBE_ADMIN_PASSWORD      - initial admin web-UI password (sensitive)
#
# Optional (when this module creates the RDS backing store, i.e. RDS_ENDPOINT empty):
#   VPC_ID, VPC_SUBNET_IDS (comma-sep), VPC_CIDR_BLOCK
# Optional (when targeting an existing Postgres):
#   RDS_ENDPOINT, RDS_USERNAME, RDS_PASSWORD
#
# Idempotent: re-runs reconcile state with the AWS / EKS side.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"
: "${EKS_CLUSTER_NAME:?EKS_CLUSTER_NAME is required}"
: "${SONARQUBE_ADMIN_PASSWORD:?SONARQUBE_ADMIN_PASSWORD is required}"

export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_aws_access_key_id="${AWS_ACCESS_KEY_ID}"
export TF_VAR_aws_secret_access_key="${AWS_SECRET_ACCESS_KEY}"
export TF_VAR_eks_cluster_name="${EKS_CLUSTER_NAME}"
export TF_VAR_sonarqube_admin_password="${SONARQUBE_ADMIN_PASSWORD}"
[[ -n "${RDS_ENDPOINT:-}" ]] && export TF_VAR_rds_endpoint="${RDS_ENDPOINT}"
[[ -n "${RDS_USERNAME:-}" ]] && export TF_VAR_rds_username="${RDS_USERNAME}"
[[ -n "${RDS_PASSWORD:-}" ]] && export TF_VAR_rds_password="${RDS_PASSWORD}"
[[ -n "${VPC_ID:-}" ]] && export TF_VAR_vpc_id="${VPC_ID}"
[[ -n "${VPC_SUBNET_IDS:-}" ]] && export TF_VAR_vpc_subnet_ids="[\"${VPC_SUBNET_IDS//,/\",\"}\"]"
[[ -n "${VPC_CIDR_BLOCK:-}" ]] && export TF_VAR_vpc_cidr_block="${VPC_CIDR_BLOCK}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: sonarqube source-side runtime apply complete."
echo "Outputs:"
terraform output
