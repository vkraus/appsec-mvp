#!/usr/bin/env bash
# Populate AWS WAF connector secrets into the mvp-connectors scope.
#
# Reads from environment variables:
#   WAF_LOG_BUCKET            — S3 bucket the Firehose-to-S3 logs land in
#                               (consumed by the log-stream autoloader)
#   AWS_WAF_IAM_ROLE_ARN      — IAM role ARN for the SDK fallback path
#                               (boto3 wafv2 GetSampledRequests)
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${WAF_LOG_BUCKET:?WAF_LOG_BUCKET is required}"
: "${AWS_WAF_IAM_ROLE_ARN:?AWS_WAF_IAM_ROLE_ARN is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" waf_log_bucket          --string-value "$WAF_LOG_BUCKET"
databricks secrets put-secret "$SCOPE" aws_waf_iam_role_arn    --string-value "$AWS_WAF_IAM_ROLE_ARN"

echo "OK: aws_waf secrets loaded into scope $SCOPE"
