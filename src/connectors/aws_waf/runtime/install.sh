#!/usr/bin/env bash
# Source-side install for the aws_waf waf runtime.
#
# Sub-shape: terraform-aws-bucket-policy.
#
# This runtime DOES NOT create the WebACL, the Firehose delivery stream,
# or the destination S3 bucket. Those are user prerequisites. What it
# DOES create is the S3 bucket policy that grants the Firehose service
# principal write access to the bucket, scoped by aws:SourceAccount.
#
# Required environment variables (consumed by terraform via TF_VAR_*):
#   CATALOG                 — Unity Catalog name (e.g. appsec_mvp)
#   AWS_WAF_ACCOUNT_ID      — AWS account ID hosting the WebACLs and Firehose
#   AWS_WAF_LOG_BUCKET_ARN  — ARN of the destination S3 bucket
#                             (e.g. arn:aws:s3:::my-org-waf-logs)
#
# Optional:
#   AWS_REGION              — default: us-east-1
#
# Prerequisites:
#   - WAFv2 enabled in $AWS_WAF_ACCOUNT_ID, fronting CloudFront, ALB, or APIGW.
#   - WebACL configured with logging enabled, sending logs via Kinesis
#     Firehose to the target S3 bucket.
#   - The target bucket exists and is owned by the user (in the same
#     account as the Firehose).
#   - AWS credentials usable from terraform with permissions to attach an
#     S3 bucket policy on the target bucket.
#   - For runtime ingestion: AWS credentials with `s3:GetObject` on the
#     log bucket loaded into the Databricks `mvp-connectors` scope via
#     `bash ../scripts/load-secrets.sh`.
#
# Idempotent: re-runs reconcile the bucket policy.

set -euo pipefail

: "${CATALOG:?CATALOG is required (e.g. appsec_mvp)}"
: "${AWS_WAF_ACCOUNT_ID:?AWS_WAF_ACCOUNT_ID is required}"
: "${AWS_WAF_LOG_BUCKET_ARN:?AWS_WAF_LOG_BUCKET_ARN is required (e.g. arn:aws:s3:::my-org-waf-logs)}"

export TF_VAR_catalog="${CATALOG}"
export TF_VAR_aws_waf_account_id="${AWS_WAF_ACCOUNT_ID}"
export TF_VAR_aws_waf_log_bucket_arn="${AWS_WAF_LOG_BUCKET_ARN}"
[[ -n "${AWS_REGION:-}" ]] && export TF_VAR_aws_region="${AWS_REGION}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${SCRIPT_DIR}"

terraform init -input=false
terraform apply -input=false -auto-approve

echo "OK: aws_waf source-side runtime apply complete (bucket policy attached)."
echo "Outputs:"
terraform output
