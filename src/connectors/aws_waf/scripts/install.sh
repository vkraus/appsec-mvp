#!/usr/bin/env bash
set -euo pipefail
: "${AWS_WAF_ACCOUNT_ID:?required}"
: "${AWS_WAF_LOG_BUCKET_ARN:?required}"
: "${AWS_ACCESS_KEY_ID:?required}"
: "${AWS_SECRET_ACCESS_KEY:?required}"

echo "Step 1/3: Loading secrets..."
bash src/connectors/aws_waf/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run aws-waf-connector --target dev
echo "Step 3/3: Run verification SQL — see runbook"
echo "✓ AWS WAF connector install complete."
