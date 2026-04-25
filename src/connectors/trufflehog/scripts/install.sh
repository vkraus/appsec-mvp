#!/usr/bin/env bash
# End-to-end TruffleHog connector install orchestrator.
#
# Pre-conditions:
#   - Phase 1 platform bootstrap is complete (catalog, mvp-connectors scope, silver schema).
#   - At least one SCM connector has been installed and run so silver.repositories is populated.
#   - TRUFFLEHOG_ARTIFACT_BUCKET is exported (S3 bucket or UC Volume path).
#   - If the bucket is S3: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are exported.
#   - At least one TruffleHog --json artefact is dropped at the configured location.
set -euo pipefail

echo "Step 1/3: Loading secrets..."
bash src/connectors/trufflehog/scripts/load-secrets.sh
echo "Step 2/3: Triggering pipeline..."
databricks bundle run trufflehog-connector --target dev
echo "Step 3/3: Run verification SQL — see runbook"
echo "OK: TruffleHog connector install complete."
