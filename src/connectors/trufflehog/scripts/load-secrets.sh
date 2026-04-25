#!/usr/bin/env bash
# Populate TruffleHog connector secrets into the mvp-connectors scope.
#
# TruffleHog is a CLI-artefact connector: scans run on CI/CD runners and
# write `--json` line-delimited output to a Databricks Volume or S3 bucket.
# The connector reads from that location autoloader-style.
#
# Reads from environment variables:
#   TRUFFLEHOG_ARTIFACT_BUCKET — S3 bucket name OR UC Volume URI holding
#                                the trufflehog/ prefixed line-delimited
#                                JSON artefacts.
#   AWS_ACCESS_KEY_ID          — optional. Required when the artefact
#   AWS_SECRET_ACCESS_KEY      — optional. location is an S3 bucket the
#                                Databricks workspace cannot read via its
#                                instance profile. Skip when the location
#                                is a UC Volume (Databricks-internal IAM).
#
# Idempotent: re-runs update existing secret values.

set -euo pipefail

: "${TRUFFLEHOG_ARTIFACT_BUCKET:?TRUFFLEHOG_ARTIFACT_BUCKET is required}"

SCOPE="mvp-connectors"

databricks secrets put-secret "$SCOPE" trufflehog_artifact_bucket --string-value "$TRUFFLEHOG_ARTIFACT_BUCKET"

if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  CREDS=$(printf '{"access_key_id":"%s","secret_access_key":"%s"}' "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY")
  databricks secrets put-secret "$SCOPE" trufflehog_aws_credentials --string-value "$CREDS"
  echo "OK: trufflehog secrets loaded into scope $SCOPE (incl. AWS credentials)"
else
  echo "OK: trufflehog secrets loaded into scope $SCOPE (no AWS credentials; UC Volume mode)"
fi
