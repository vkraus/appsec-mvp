#!/usr/bin/env bash
# Populate TruffleHog connector secrets into the mvp-connectors scope.
#
# TruffleHog is a CLI-artefact connector: scans run on CI/CD runners and
# write `--json` line-delimited output to a Databricks Volume. The connector
# reads from that volume; no live TruffleHog API token is required. The
# only deployment input is the artefact bucket / volume name.
#
# Reads from environment variables:
#   TRUFFLEHOG_ARTIFACT_BUCKET — S3 bucket (or volume URI) holding the
#                                trufflehog/ prefixed line-delimited JSON
#                                artefacts.
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${TRUFFLEHOG_ARTIFACT_BUCKET:?TRUFFLEHOG_ARTIFACT_BUCKET is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" trufflehog_artifact_bucket --string-value "$TRUFFLEHOG_ARTIFACT_BUCKET"

echo "OK: trufflehog secrets loaded into scope $SCOPE"
