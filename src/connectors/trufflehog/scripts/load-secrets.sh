#!/usr/bin/env bash
# Load TruffleHog artefact-bucket reader credentials into a Databricks secret
# scope.
#
# TruffleHog is a CLI-artefact connector — scans run on CI/CD runners and
# write `--json` line-delimited output to a cloud bucket; the connector
# ingests those artefacts via a Unity Catalog Volume that maps onto the
# bucket. The runtime needs read credentials for the bucket so autoloader
# can pull the JSON. We store them as a single JSON blob under one secret
# key so the runtime references one secret, not two.
#
# Reads from environment variables:
#   AWS_ACCESS_KEY_ID                         — bucket reader access key
#   AWS_SECRET_ACCESS_KEY                     — bucket reader secret key
#   TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE   — optional; default mvp-connectors
#   TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY     — optional; default trufflehog_aws_credentials
#
# Idempotent: re-runs replace the secret value.

set -euo pipefail

SCOPE="${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_SCOPE:-mvp-connectors}"
KEY="${TRUFFLEHOG_ARTIFACT_VOLUME_SECRET_KEY:-trufflehog_aws_credentials}"

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID env var required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY env var required}"

CREDS=$(jq -nc \
  --arg ak "$AWS_ACCESS_KEY_ID" \
  --arg sk "$AWS_SECRET_ACCESS_KEY" \
  '{access_key_id:$ak, secret_access_key:$sk}')

echo "Loading TruffleHog AWS credentials into Databricks secret scope '$SCOPE' key '$KEY'..."
echo -n "$CREDS" | databricks secrets put-secret --scope "$SCOPE" --key "$KEY"
echo "OK: TruffleHog artefact-bucket credentials loaded."
