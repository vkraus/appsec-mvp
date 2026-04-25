#!/usr/bin/env bash
# One-time post-bundle-deploy bootstrap for the appsec-mvp platform layer.
#
# Creates the cross-cutting Databricks objects DAB has no native type for:
#   - Secret-scope container `mvp-connectors`
#   - Storage credential pointing at the operator-supplied UC IAM role
#   - External location pointing at the operator-supplied S3 artifact bucket
#
# Per-connector secret values are NOT loaded here. Each connector ships its
# own scripts/load-secrets.sh that populates the keys that connector reads.
#
# Reads from environment variables:
#   EXTERNAL_LOCATION_ROLE_ARN  — IAM role ARN for the UC external location
#   ARTIFACT_BUCKET             — S3 bucket name (no s3:// prefix)
#   CATALOG                     — catalog name (e.g. appsec_dev)
#
# Idempotent: re-runs are safe.

set -euo pipefail

: "${EXTERNAL_LOCATION_ROLE_ARN:?EXTERNAL_LOCATION_ROLE_ARN is required}"
: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${CATALOG:?CATALOG is required}"

SCOPE="mvp-connectors"

# Secret scope (idempotent — create-scope errors if exists; we tolerate that).
echo "==> Creating secret scope: $SCOPE"
databricks secrets create-scope "$SCOPE" 2>&1 | grep -v "RESOURCE_ALREADY_EXISTS" || true

# Storage credential
echo "==> Creating storage credential: ${CATALOG}-artifacts"
databricks unity-catalog storage-credentials create \
  --json "$(cat <<EOF
{
  "name": "${CATALOG}-artifacts",
  "aws_iam_role": { "role_arn": "${EXTERNAL_LOCATION_ROLE_ARN}" },
  "comment": "Access the scanner-artifact S3 bucket from Unity Catalog"
}
EOF
)" 2>&1 | grep -v "ALREADY_EXISTS" || true

# External location
echo "==> Creating external location: ${CATALOG}_artifacts"
databricks unity-catalog external-locations create \
  --json "$(cat <<EOF
{
  "name": "${CATALOG}_artifacts",
  "url": "s3://${ARTIFACT_BUCKET}/",
  "credential_name": "${CATALOG}-artifacts",
  "comment": "Scanner artifact bucket (operator-supplied)"
}
EOF
)" 2>&1 | grep -v "ALREADY_EXISTS" || true

echo "OK: platform bootstrap complete."
echo "Next: populate per-connector secrets via src/connectors/<source>/scripts/load-secrets.sh"
echo "Then: databricks bundle run platform-bootstrap   (creates silver tables)"
