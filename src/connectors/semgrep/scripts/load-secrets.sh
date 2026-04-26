#!/usr/bin/env bash
# Populate semgrep connector secrets into the mvp-connectors scope.
# semgrep doesn't expose an API — the connector reads JSON / SARIF findings
# from an object-storage prefix that the semgrep runner writes to.
#
# Reads from environment variables:
#   ARTIFACT_BUCKET
#   SEMGREP_PREFIX
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${SEMGREP_PREFIX:?SEMGREP_PREFIX is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" semgrep_artifact_bucket --string-value "$ARTIFACT_BUCKET"
databricks secrets put-secret "$SCOPE" semgrep_artifact_prefix --string-value "$SEMGREP_PREFIX"

echo "OK: semgrep secrets loaded into scope $SCOPE"
