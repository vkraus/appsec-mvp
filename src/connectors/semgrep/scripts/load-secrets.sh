#!/usr/bin/env bash
# Populate Semgrep connector secrets into the mvp-connectors scope.
#
# Semgrep doesn't expose an API — the connector reads JSON findings
# from an S3 bucket prefix that the Semgrep CronJob writes to.
#
# Reads from environment variables:
#   ARTIFACT_BUCKET   — S3 bucket where Semgrep writes findings (no s3:// prefix)
#   SEMGREP_PREFIX    — optional; key prefix within the bucket (default: semgrep/)
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
SEMGREP_PREFIX="${SEMGREP_PREFIX:-semgrep/}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" semgrep_artifact_bucket --string-value "$ARTIFACT_BUCKET"
databricks secrets put-secret "$SCOPE" semgrep_artifact_prefix --string-value "$SEMGREP_PREFIX"

echo "OK: semgrep secrets loaded into scope $SCOPE"
